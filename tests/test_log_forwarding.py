# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Audit forwarding to an XDR or a SIEM: syslog, HTTP POST, and what must not leak.

The forwarder is the part of the product that talks to the outside world on
every login, so it is tested twice over: functionally (an event really arrives
in the shape a collector expects) and defensively (a secret never leaves, a
forged line never splits a record, a dead collector never slows a request).
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.conftest import csrf_headers, login_user, make_admin, quiz_payload, register_user

SETTINGS = "/api/v1/admin/settings"


# --------------------------------------------------------------------------- #
# Collectors used by the tests: a real HTTP server and a real UDP socket


class _Collector(BaseHTTPRequestHandler):
    """Records every POST it receives and answers 202.

    The answer is complete (length and an explicit close): a collector that
    leaves httpx waiting for a body would stall the forwarding thread, and the
    test would then measure a hung worker instead of the forwarder.
    """

    protocol_version = "HTTP/1.1"
    received: list[dict] = []

    def do_POST(self):  # noqa: N802 - the name is imposed by http.server
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append(
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
                "json": json.loads(body or b"{}"),
            }
        )
        self.send_response(202)
        self.send_header("Content-Length", "2")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):  # a silent collector, not a chatty one
        return


@pytest.fixture()
def http_collector():
    """A collector on a real port: the forwarder speaks real HTTP to it."""
    _Collector.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/ingest", _Collector.received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def syslog_collector():
    """A UDP syslog listener: whatever the forwarder sends, one datagram each."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.2)
    datagrams: list[bytes] = []
    stop = threading.Event()

    def collect():
        while not stop.is_set():
            try:
                datagrams.append(sock.recv(65535))
            except TimeoutError:
                continue
            except OSError:  # socket closed at teardown
                return

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1], datagrams
    finally:
        stop.set()
        thread.join(timeout=2)
        sock.close()


# --------------------------------------------------------------------------- #
# Helpers


@pytest.fixture(autouse=True)
def clean_forwarder():
    """Counters and backoff are module state: a test must not lend them onwards."""
    from app import log_forward

    log_forward.flush(2)
    for key in ("queued", "sent", "dropped", "failed"):
        log_forward._state[key] = 0
    log_forward._state["last_error"] = ""
    log_forward._backoff_until = 0.0
    log_forward._consecutive_failures = 0
    yield
    log_forward.flush(2)


def _admin(client, email: str = "root@example.com") -> None:
    register_user(client, email, display_name="Root")
    make_admin(client)


def _configure(client, **values) -> None:
    response = client.put(SETTINGS, json={"values": values}, headers=csrf_headers(client))
    assert response.status_code == 200, response.text


def _events(received: list[dict]) -> list[dict]:
    return [event for request in received for event in request["json"]["events"]]


def _named(received: list[dict], name: str) -> list[dict]:
    return [event for event in _events(received) if event["event"] == name]


def _wait_named(received: list[dict], name: str, timeout: float = 6.0) -> dict:
    """Wait until an event called ``name`` reached the collector."""
    from app import log_forward

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _named(received, name)
        if found:
            return found[0]
        time.sleep(0.02)
    log_forward.flush(2)
    found = _named(received, name)
    assert found, f"{name} never arrived; got {[e['event'] for e in _events(received)]}"
    return found[0]


def _wait_datagram(datagrams: list[bytes], marker: bytes, timeout: float = 6.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for datagram in datagrams:
            if marker in datagram:
                return datagram.decode("utf-8")
        time.sleep(0.02)
    raise AssertionError(f"no datagram carried {marker!r}; got {[d[:60] for d in datagrams]}")


def _account(client, email: str = "player@example.com") -> None:
    """The account exists, and login has not happened yet."""
    register_user(client, email, display_name="Player One")


# --------------------------------------------------------------------------- #
# Nothing leaves unless an administrator asked for it


def test_a_disabled_forwarder_sends_nothing(client, http_collector):
    url, received = http_collector
    _admin(client)
    # A target is set, the switch is off: this is the default state of a fresh
    # instance, and it must stay silent.
    _configure(client, **{"log.enabled": False, "log.http_url": url})

    _account(client)
    login_user(client, "player@example.com")

    from app import log_forward

    log_forward.flush(1)
    assert _events(received) == []
    assert log_forward.status()["configured"] is False


def test_a_target_without_the_switch_stays_silent(client, http_collector):
    url, received = http_collector
    _admin(client)
    _configure(client, **{"log.enabled": True})

    _account(client)
    login_user(client, "player@example.com")

    from app import log_forward

    log_forward.flush(1)
    assert _events(received) == []
    assert log_forward.status()["targets"] == {"syslog": False, "http": False}


# --------------------------------------------------------------------------- #
# A real event, in the shape a collector expects


def test_a_login_arrives_as_one_json_event(client, http_collector):
    url, received = http_collector
    _account(client, "someone@example.com")
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url})

    assert login_user(client, "someone@example.com").status_code == 200
    event = _wait_named(received, "login_success")

    request = received[0]
    assert request["path"] == "/ingest"
    assert request["headers"]["content-type"] == "application/json"
    assert request["json"]["source"] == "openlearn"
    assert request["json"]["schema"] == "openlearn.audit/1"
    assert event["outcome"] == "success"
    assert event["actor"]["email"] == "someone@example.com"
    assert event["actor"]["role"] == "user"
    assert event["ip"]  # the collector needs the source address to correlate
    assert event["ts"].endswith("Z")
    assert len(_named(received, "login_success")) == 1


def test_the_collector_receives_the_bearer_token_and_not_in_the_body(client, http_collector):
    url, received = http_collector
    _account(client)
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url, "log.http_token": "s3cr3t-hedgehog"})

    login_user(client, "player@example.com")
    _wait_named(received, "login_success")

    request = next(r for r in received if _named([r], "login_success"))
    assert request["headers"]["authorization"] == "Bearer s3cr3t-hedgehog"
    assert b"s3cr3t-hedgehog" not in request["body"]


def test_syslog_carries_rfc5424_with_structured_data(client, syslog_collector):
    port, datagrams = syslog_collector
    _account(client, "audited@example.com")
    _admin(client)
    _configure(
        client,
        **{
            "log.enabled": True,
            "log.syslog_host": "127.0.0.1",
            "log.syslog_port": port,
            "log.syslog_protocol": "udp",
            "log.syslog_facility": 13,  # log audit
            "log.syslog_hostname": "openlearn-test",
        },
    )

    login_user(client, "audited@example.com")
    line = _wait_datagram(datagrams, b"login_success")

    # facility 13 * 8 + severity 6 = 110
    assert line.startswith("<110>1 ")
    assert "\n" not in line
    assert " openlearn-test openlearn - login_success [openlearn@32473 " in line
    assert 'event="login_success"' in line
    assert 'actor_email="audited@example.com"' in line
    message = json.loads("{" + line.split("] {", 1)[1])
    assert message["event"] == "login_success"


def test_both_targets_are_served(client, http_collector, syslog_collector):
    url, received = http_collector
    port, datagrams = syslog_collector
    _account(client)
    _admin(client)
    _configure(
        client,
        **{
            "log.enabled": True,
            "log.http_url": url,
            "log.syslog_host": "127.0.0.1",
            "log.syslog_port": port,
        },
    )

    login_user(client, "player@example.com")
    _wait_named(received, "login_success")
    assert "login_success" in _wait_datagram(datagrams, b"login_success")


# --------------------------------------------------------------------------- #
# A secret never travels


def test_no_field_named_like_a_secret_is_forwarded():
    from app import log_forward

    event = log_forward.build_event(
        "login_failure",
        outcome="failure",
        detail={
            "password": "hunter2",
            "note": "wrong password",
            "reset_token": "abcdef",
            "nested": {"cookie": "ol_session=xyz", "authorization": "Bearer abc", "safe": "kept"},
            "items": [{"api_key": "k-123"}, {"otp": "000111"}],
        },
    )
    text = json.dumps(event)
    for secret in ("hunter2", "abcdef", "ol_session=xyz", "Bearer abc", "k-123", "000111"):
        assert secret not in text
    assert event["detail"]["nested"]["safe"] == "kept"
    assert event["detail"]["note"] == "wrong password"


def test_the_settings_api_masks_the_collector_token(client):
    _admin(client)
    _configure(client, **{"log.http_token": "s3cr3t-hedgehog"})

    sections = client.get(SETTINGS).json()["sections"]
    entry = next(item for item in sections["log"] if item["key"] == "log.http_token")
    assert entry["is_set"] is True
    assert entry["value"] in (None, "", "[redacted]")
    assert "s3cr3t-hedgehog" not in json.dumps(sections)


def test_changing_a_setting_forwards_the_key_names_only(client, http_collector):
    url, received = http_collector
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url})
    _wait_named(received, "settings_changed")

    _configure(client, **{"log.http_token": "s3cr3t-hedgehog"})

    from app import log_forward

    deadline = time.monotonic() + 6
    target = None
    while time.monotonic() < deadline:
        for event in _named(received, "settings_changed"):
            note = (event.get("detail") or {}).get("note", "")
            if "log.http_token" in note:
                target = event
                break
        if target:
            break
        time.sleep(0.02)
    log_forward.flush(2)
    assert target is not None
    assert "s3cr3t-hedgehog" not in json.dumps(target)


# --------------------------------------------------------------------------- #
# A line stays a line, a queue stays bounded


def test_a_newline_in_content_cannot_forge_a_second_syslog_record():
    from app import log_forward, runtime

    config = runtime.LogConfig(
        enabled=True,
        syslog_host="127.0.0.1",
        syslog_port=514,
        syslog_protocol="udp",
        syslog_facility=13,
        syslog_hostname="host] <34>1 forged",
        syslog_tls_verify=True,
        http_url="",
        http_token="",
        http_verify_tls=True,
        http_timeout_seconds=5,
    )
    event = log_forward.build_event(
        "quiz_deleted\n<34>1 2026-01-01T00:00:00Z forged host openlearn - evil",
        detail={"name": "line one\r\n<34>1 forged"},
        target={"type": "quiz", "id": 7, "name": "a\nb"},
    )
    line = log_forward.rfc5424(event, config).decode("utf-8")

    # One datagram is one line: a newline inside a title cannot start a second
    # record, and a bracket in the hostname cannot close the structured data.
    assert "\n" not in line and "\r" not in line
    assert line.startswith("<110>1 ")
    # The hostname is escaped, so the structured data ends where it should.
    assert "host\\] <34>1 forged" in line
    assert 'event="quiz_deleted <34>1' in line  # kept inside the SD value
    message = json.loads("{" + line.split("] {", 1)[1])
    assert message["detail"]["name"] == "line one  <34>1 forged"


def test_a_full_queue_drops_the_event_instead_of_growing(monkeypatch):
    from app import log_forward

    full: queue.Queue = queue.Queue(maxsize=1)
    full.put({"already": "there"})
    monkeypatch.setattr(log_forward, "_ensure_worker", lambda: full)
    monkeypatch.setattr(
        log_forward,
        "runtime",
        type("R", (), {"log_config": staticmethod(lambda: _EnabledLogConfig())}),
    )

    assert log_forward.emit("login_success") is False
    assert log_forward.status()["dropped"] >= 1


class _EnabledLogConfig:
    enabled = True
    syslog_host = ""
    http_url = "http://127.0.0.1:9/ingest"
    configured = True


# --------------------------------------------------------------------------- #
# A collector that is down costs an event, never a page


def test_a_dead_collector_does_not_fail_the_login(client):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    _account(client)
    _admin(client)
    _configure(
        client,
        **{
            "log.enabled": True,
            "log.http_url": f"http://127.0.0.1:{dead_port}/ingest",
            "log.http_timeout_seconds": 1,
        },
    )

    started = time.monotonic()
    assert login_user(client, "player@example.com").status_code == 200
    assert time.monotonic() - started < 5  # the request never waits for the collector

    from app import log_forward

    log_forward.flush(4)
    status = log_forward.status()
    assert status["failed"] >= 1
    assert status["dropped"] >= 1
    assert "http" in status["last_error"]


def test_a_broken_syslog_target_does_not_silence_the_http_one(client, http_collector):
    url, received = http_collector
    _account(client)
    _admin(client)
    _configure(
        client,
        **{
            "log.enabled": True,
            "log.http_url": url,
            "log.syslog_host": "127.0.0.1",
            "log.syslog_port": 9,
            "log.syslog_protocol": "tcp",
        },
    )

    login_user(client, "player@example.com")
    _wait_named(received, "login_success")

    from app import log_forward

    assert "syslog" in log_forward.status()["last_error"]


# --------------------------------------------------------------------------- #
# Validation and access


@pytest.mark.parametrize(
    "values",
    [
        {"log.http_url": "file:///etc/passwd"},
        {"log.http_url": "gopher://127.0.0.1/"},
        {"log.syslog_protocol": "carrier-pigeon"},
        {"log.syslog_port": 70000},
        {"log.syslog_facility": 42},
        {"log.http_timeout_seconds": 0},
    ],
)
def test_a_target_that_makes_no_sense_is_refused(client, values):
    _admin(client)
    response = client.put(SETTINGS, json={"values": values}, headers=csrf_headers(client))
    assert response.status_code == 422, response.text


def test_only_an_administrator_reads_or_tests_the_forwarder(client):
    _account(client)
    login_user(client, "player@example.com")  # a plain account, not an administrator
    assert client.get("/api/v1/admin/log/status").status_code == 403
    assert client.post("/api/v1/admin/log/test", json={}, headers=csrf_headers(client)).status_code == 403


def test_a_visitor_cannot_read_the_status(client):
    assert client.get("/api/v1/admin/log/status").status_code in (401, 403)


def test_the_test_endpoint_proves_each_target_and_leaves_a_trace(client, http_collector, syslog_collector):
    url, received = http_collector
    port, datagrams = syslog_collector
    _admin(client)
    _configure(
        client,
        **{"log.enabled": True, "log.http_url": url, "log.syslog_host": "127.0.0.1", "log.syslog_port": port},
    )

    response = client.post("/api/v1/admin/log/test", json={}, headers=csrf_headers(client))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is True
    assert result["targets"] == {"syslog": "ok", "http": "ok"}

    assert _wait_named(received, "audit.test")["detail"]["message"]
    assert "audit.test" in _wait_datagram(datagrams, b"audit.test")

    # The test itself is an auditable action: it appears in the local trail.
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SecurityEvent

    with SessionLocal() as db:
        events = [row.event for row in db.scalars(select(SecurityEvent)).all()]
    assert "audit_test_sent" in events


def test_the_status_reports_targets_counters_and_queue_size(client, http_collector):
    url, _received = http_collector
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url})

    body = client.get("/api/v1/admin/log/status").json()
    assert body["configured"] is True
    assert body["targets"] == {"syslog": False, "http": True}
    for key in ("sent", "dropped", "failed", "pending", "queue_max", "paused_seconds"):
        assert key in body


# --------------------------------------------------------------------------- #
# The actions the user asked to see in the SIEM


def test_creating_and_deleting_content_is_forwarded_with_its_name(client, http_collector):
    url, received = http_collector
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url})

    payload = quiz_payload(title="SIEM visible quiz")
    created = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    assert _wait_named(received, "quiz_created")["target"]["name"] == "SIEM visible quiz"

    deleted = client.delete(f"/api/v1/quizzes/{quiz_id}", headers=csrf_headers(client))
    assert deleted.status_code in (200, 204)
    event = _wait_named(received, "quiz_deleted")
    assert event["target"]["type"] == "quiz"
    assert event["target"]["id"] == str(quiz_id)
    assert event["target"]["name"] == "SIEM visible quiz"
    assert event["actor"]["email"] == "root@example.com"


def test_an_ai_call_is_forwarded_without_the_prompt(client, http_collector, monkeypatch):
    url, received = http_collector
    _admin(client)
    _configure(client, **{"log.enabled": True, "log.http_url": url})

    from app import ai as ai_module
    from app import runtime
    from app.config import settings

    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_model", "fake-model")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake-provider/v1")
    # The settings cache holds the previous, disabled value for three seconds.
    runtime.invalidate()

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "an answer"}, "finish_reason": "stop"}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *_args, **_kwargs):
            return _Response()

    # Patch the module's view of httpx, not httpx itself: the forwarder posts
    # through the same library, and a fake Client would silently swallow it.
    shim = type(
        "HttpxShim",
        (),
        {
            "Client": _Client,
            "HTTPError": ai_module.httpx.HTTPError,
            "HTTPStatusError": ai_module.httpx.HTTPStatusError,
            "Response": ai_module.httpx.Response,
        },
    )
    monkeypatch.setattr(ai_module, "httpx", shim)
    answer = ai_module._chat([{"role": "user", "content": "secret prompt about a pupil"}], operation="translate")
    assert answer == "an answer"

    event = _wait_named(received, "ai_call")
    assert event["detail"]["operation"] == "translate"
    assert event["detail"]["model"] == "fake-model"
    assert "seconds" in event["detail"]
    assert "secret prompt" not in json.dumps(event)
