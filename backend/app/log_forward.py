# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Ship audit events to an XDR or a SIEM, over syslog or HTTP POST.

An instance that runs next to a Splunk, a Sentinel, a SecOps or a Sekoia
already has somewhere to collect security events; this module hands them over in
the shape those collectors expect, without making the product depend on any of
them.

Five rules, and each one is a test:

* **A request never waits on the collector.** ``emit`` only appends to a bounded
  in-memory queue; a daemon thread delivers. A collector that hangs, refuses or
  disappears costs a dropped event, never a slow page.
* **No secret leaves the process.** Field names are scrubbed before anything is
  serialised, and the values of token, password, cookie and key fields never
  enter an event.
* **A log line is one line.** Control characters and newlines are stripped, so a
  quiz titled ``foo\\n<34>1 ...`` cannot forge a second syslog record.
* **A failing target never silences the other.** Syslog and HTTP are delivered
  independently; one can be down while the other keeps working.
* **A broken collector must not become a load amplifier.** After repeated
  failures the sender backs off, drops events rather than buffering for ever,
  and counts what it dropped so an administrator can see it.

RFC 5424 is used for syslog (the format rsyslog, syslog-ng and every SIEM
appliance accept); HTTP POST carries a JSON body of the same events.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import socket
import ssl
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from . import runtime

logger = logging.getLogger(__name__)

#: An event is a small dict; the queue is there to absorb a burst, not a flood.
QUEUE_MAX = 2000
#: Bytes of the message part, and characters of any single field.
MAX_FIELD = 300
#: After this many consecutive failures, stop trying for a while.
FAILURE_THRESHOLD = 5
BACKOFF_START = 30.0
BACKOFF_MAX = 300.0

#: A field whose name matches is replaced by "[redacted]" whatever it holds.
_SECRET_NAME = re.compile(
    r"(pass|passwd|secret|token|cookie|session|authorization|api[_-]?key|credential|otp)",
    re.IGNORECASE,
)
#: Everything a syslog line cannot contain: it would break the framing.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_queue: queue.Queue[dict[str, Any]] | None = None
_worker: threading.Thread | None = None
_lock = threading.Lock()
_state = {
    "queued": 0,
    "sent": 0,
    "dropped": 0,
    "failed": 0,
    "last_error": "",
    "last_sent_at": None,
}
_backoff_until = 0.0
_consecutive_failures = 0


# --------------------------------------------------------------------------- #
# Shaping one event


def clean_text(value: Any, limit: int = MAX_FIELD) -> str:
    """One line, no control characters, bounded, never ``None``."""
    text = "" if value is None else str(value)
    text = _CONTROL.sub(" ", text).strip()
    return text[:limit]


def scrub(detail: Any, depth: int = 0) -> Any:
    """Drop secrets and keep every string on one line.

    Called on everything that leaves the process, so it does not matter whether
    a caller forgot: a key named ``password`` or ``reset_token`` is replaced
    whatever it contains, at any depth.
    """
    if depth > 3:
        return "[truncated]"
    if isinstance(detail, dict):
        cleaned: dict[str, Any] = {}
        for key, value in detail.items():
            name = clean_text(key, 60)
            if _SECRET_NAME.search(name):
                cleaned[name] = "[redacted]"
            else:
                cleaned[name] = scrub(value, depth + 1)
        return cleaned
    if isinstance(detail, (list, tuple)):
        return [scrub(item, depth + 1) for item in detail[:20]]
    if isinstance(detail, bool) or detail is None:
        return detail
    if isinstance(detail, (int, float)):
        return detail
    return clean_text(detail)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_event(
    event: str,
    *,
    outcome: str = "success",
    actor: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    detail: Any = None,
    ip: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    """The event as every collector sees it: flat, bounded, no secret."""
    payload: dict[str, Any] = {
        "schema": "openlearn.audit/1",
        "ts": now(),
        "event": clean_text(event, 60),
        "outcome": clean_text(outcome, 20) or "success",
        "source": clean_text(source, 20) or "api",
    }
    if ip:
        payload["ip"] = clean_text(ip, 45)
    if actor:
        actor_id = actor.get("id")
        payload["actor"] = {
            "id": int(actor_id) if isinstance(actor_id, int) else None,
            "email": clean_text(actor.get("email"), 160) or None,
            "role": clean_text(actor.get("role"), 20) or None,
        }
    if target:
        payload["target"] = {
            "type": clean_text(target.get("type"), 30) or None,
            "id": clean_text(target.get("id"), 40) or None,
            "name": clean_text(target.get("name"), 120) or None,
        }
    if detail not in (None, "", {}):
        payload["detail"] = scrub(detail)
    return payload


# --------------------------------------------------------------------------- #
# Formatting


_FACILITY_MAX = 23


def rfc5424(payload: dict[str, Any], config: runtime.LogConfig) -> bytes:
    """``<PRI>1 TS HOST APP PID MSGID [SD] MSG`` — one datagram, one line.

    The structured data repeats what a collector filters on (event, outcome,
    actor, target) so a rule can match without parsing the JSON message.
    """
    severity = 6 if payload.get("outcome") == "success" else 4
    facility = max(0, min(_FACILITY_MAX, int(config.syslog_facility)))
    priority = facility * 8 + severity
    structured = [
        f'event="{_sd(payload.get("event"))}"',
        f'outcome="{_sd(payload.get("outcome"))}"',
    ]
    actor = payload.get("actor") or {}
    if actor.get("id") is not None:
        structured.append(f'actor="{_sd(actor.get("id"))}"')
    if actor.get("email"):
        structured.append(f'actor_email="{_sd(actor.get("email"))}"')
    target = payload.get("target") or {}
    if target.get("type"):
        structured.append(f'target_type="{_sd(target.get("type"))}"')
    if target.get("id"):
        structured.append(f'target_id="{_sd(target.get("id"))}"')
    if payload.get("ip"):
        structured.append(f'ip="{_sd(payload.get("ip"))}"')
    message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    line = (
        f"<{priority}>1 {payload['ts']} {_sd(config.syslog_hostname or 'openlearn')} "
        f"openlearn - {payload.get('event', 'event')} "
        f"[openlearn@32473 {' '.join(structured)}] {message}"
    )
    return line.encode("utf-8")


def _sd(value: Any) -> str:
    """Escape a structured-data value: ``"`` ``\\`` ``]`` would end the field."""
    text = clean_text(value, 120)
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")


# --------------------------------------------------------------------------- #
# Delivery


def _send_syslog(payload: dict[str, Any], config: runtime.LogConfig) -> None:
    line = rfc5424(payload, config)
    protocol = (config.syslog_protocol or "udp").lower()
    host, port = config.syslog_host, int(config.syslog_port)
    if protocol == "udp":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            sock.sendto(line, (host, port))
        return
    with socket.create_connection((host, port), timeout=3) as raw:
        if protocol == "tls":
            context = ssl.create_default_context()
            if not config.syslog_tls_verify:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            with context.wrap_socket(raw, server_hostname=host) as tls:
                tls.sendall(line + b"\n")
        else:
            raw.sendall(line + b"\n")


def _send_http(events: list[dict[str, Any]], config: runtime.LogConfig) -> None:
    headers = {"Content-Type": "application/json", "User-Agent": "openlearn-audit/1"}
    if config.http_token:
        # Bearer by default; collectors that want another scheme use a URL with
        # its own credential, e.g. a Splunk HEC token embedded by the operator.
        headers["Authorization"] = f"Bearer {config.http_token}"
    body = {
        "source": "openlearn",
        "schema": "openlearn.audit/1",
        "events": events,
    }
    with httpx.Client(timeout=int(config.http_timeout_seconds), verify=config.http_verify_tls) as client:
        response = client.post(config.http_url, json=body, headers=headers)
        response.raise_for_status()


def _deliver(batch: list[dict[str, Any]], config: runtime.LogConfig) -> dict[str, str]:
    """Try every configured target; report each one separately."""
    results: dict[str, str] = {}
    if config.syslog_host:
        try:
            for payload in batch:
                _send_syslog(payload, config)
            results["syslog"] = "ok"
        except Exception as exc:  # a collector is external: never fatal
            results["syslog"] = f"{type(exc).__name__}: {clean_text(exc, 120)}"
    if config.http_url:
        try:
            _send_http(batch, config)
            results["http"] = "ok"
        except Exception as exc:  # pragma: no cover - depends on the collector
            results["http"] = f"{type(exc).__name__}: {clean_text(exc, 120)}"
    return results


# --------------------------------------------------------------------------- #
# The queue and its worker


def _ensure_worker() -> queue.Queue[dict[str, Any]]:
    global _queue, _worker
    with _lock:
        if _queue is None:
            _queue = queue.Queue(maxsize=QUEUE_MAX)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="audit-forward", daemon=True)
            _worker.start()
        return _queue


def _loop() -> None:
    global _backoff_until, _consecutive_failures
    while True:
        batch: list[dict[str, Any]] = []
        try:
            first = _queue.get(timeout=1.0) if _queue is not None else None
        except queue.Empty:
            continue
        if first is None:
            continue
        batch.append(first)
        # Drain what arrived meanwhile: one syslog connection, one HTTP request.
        while len(batch) < 50:
            try:
                nxt = _queue.get_nowait()
            except queue.Empty:
                break
            batch.append(nxt)

        config = runtime.log_config()
        if not config.configured:
            _state["dropped"] += len(batch)
            continue

        now_monotonic = time.monotonic()
        if now_monotonic < _backoff_until:
            _state["dropped"] += len(batch)
            continue

        results = _deliver(batch, config)
        failed = {name: error for name, error in results.items() if error != "ok"}
        if failed:
            _consecutive_failures += 1
            _state["failed"] += len(batch)
            _state["last_error"] = "; ".join(f"{name}: {error}" for name, error in failed.items())[:300]
            if _consecutive_failures >= FAILURE_THRESHOLD:
                wait = min(BACKOFF_MAX, BACKOFF_START * (2 ** (_consecutive_failures - FAILURE_THRESHOLD)))
                _backoff_until = now_monotonic + wait
                logger.warning("Audit forwarding paused for %.0fs after repeated failures", wait)
            # A failed batch is gone on purpose: a collector that is down must
            # not turn this queue into an unbounded memory leak.
            _state["dropped"] += len(batch)
        else:
            _consecutive_failures = 0
            _backoff_until = 0.0
            _state["sent"] += len(batch)
            _state["last_sent_at"] = now()


def emit(
    event: str,
    *,
    outcome: str = "success",
    actor: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    detail: Any = None,
    ip: str | None = None,
    source: str = "api",
) -> bool:
    """Queue one event. Returns whether it was queued, never raises.

    Called from request handlers: it must be cheap, allocation-bounded and
    incapable of turning an audit problem into a 500.
    """
    try:
        config = runtime.log_config()
        if not config.configured:
            return False
        payload = build_event(
            event, outcome=outcome, actor=actor, target=target, detail=detail, ip=ip, source=source
        )
        events = _ensure_worker()
        try:
            events.put_nowait(payload)
        except queue.Full:
            _state["dropped"] += 1
            return False
        _state["queued"] += 1
        return True
    except Exception:  # pragma: no cover - defence in depth
        logger.warning("Audit event dropped before queueing", exc_info=False)
        return False


# --------------------------------------------------------------------------- #
# Inspection, tests, shutdown


def status() -> dict[str, Any]:
    """Counters for the administration page: what was sent, and what was lost."""
    config = runtime.log_config()
    return {
        "configured": config.configured,
        "targets": {
            "syslog": bool(config.syslog_host),
            "http": bool(config.http_url),
        },
        "queue_max": QUEUE_MAX,
        "pending": _queue.qsize() if _queue is not None else 0,
        "paused_seconds": max(0, round(_backoff_until - time.monotonic())) if _backoff_until else 0,
        **{key: _state[key] for key in ("sent", "dropped", "failed", "last_error", "last_sent_at")},
    }


def flush(timeout: float = 5.0) -> bool:
    """Wait until the queue is empty (tests, shutdown). True when it drained."""
    if _queue is None:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _queue.empty():
            # The worker may still hold the last batch in flight.
            time.sleep(0.05)
            if _queue.empty():
                return True
        time.sleep(0.02)
    return False


def send_test(*, source: str = "admin") -> dict[str, Any]:
    """Deliver one synthetic event synchronously, so an administrator can prove
    the wiring from the settings page instead of waiting for a real incident."""
    config = runtime.log_config()
    if not config.configured:
        return {"ok": False, "error": "no target configured", "targets": {}}
    payload = build_event(
        "audit.test",
        outcome="success",
        detail={"message": "test event from the administration page"},
        source=source,
    )
    results = _deliver([payload], config)
    ok = all(value == "ok" for value in results.values())
    return {"ok": ok, "targets": results, "event": payload}
