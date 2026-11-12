---
title: Audit forwarding — syslog and HTTP POST for a SIEM or an XDR
description: >-
  Send OpenLearn's security events to Splunk, Microsoft Sentinel, Google SecOps, Sekoia or any
  syslog collector: the event schema, the two transports, the exact list of actions recorded, and
  the properties the tests enforce.
permalink: /audit-logging/
---

# Audit forwarding

An instance that runs next to a SIEM already has somewhere to collect security events. OpenLearn
hands them over in the shape those collectors expect, over **syslog (RFC 5424)** or **HTTP POST**,
without depending on any of them: with no target configured, nothing leaves the process.

The same events are also written to the instance's own trail (`security_events`), readable by a
moderator in **Administration → Security log**. Forwarding is a copy, never the only record.

## What is recorded

| Event | When | Target |
| --- | --- | --- |
| `login_success`, `login_failure`, `login_locked` | Sign-in attempt, wrong password, account locked after too many attempts | — |
| `logout` | Explicit sign-out | — |
| `token_success`, `token_failure` | Machine-to-machine credential issued or refused | — |
| `register_success`, `register_conflict` | Account created, or address already taken | the account |
| `email_verified`, `email_verification_requested` | Address confirmed, confirmation sent or throttled | the account |
| `password_reset_requested`, `password_reset_completed` | Reset asked for and completed | the account |
| `sso_login`, `sso_failure` | Sign-in through an OpenID Connect or SAML provider | the provider |
| `quiz_created`, `quiz_updated`, `quiz_deleted`, `quiz_published` | Content lifecycle | the quiz, by id **and** title |
| `wiki_created`, `wiki_deleted`, `wiki_page_saved`, `wiki_page_deleted` | Space and page lifecycle | the wiki and the page |
| `deck_created`, `deck_deleted` | Revision deck lifecycle | the deck |
| `ai_call` | Every call to the model provider | operation, model, duration — never the text |
| `settings_changed` | An administrator changed settings | the **names** of the keys changed |
| `audit_test_sent` | The **Send a test event** button was used | — |

Each event carries the actor (`id`, `email`, `role`), the target (`type`, `id`, `name`), the
outcome (`success` or `failure`), the source address of the request, and a timestamp. A person
triaging an alert therefore knows *who* deleted *which* quiz, not only that a deletion happened.

## What is never recorded

- **The text of an AI prompt or answer** — only the operation, the model and the duration.
- **Any value of a field whose name looks like a secret** — `password`, `token`, `secret`,
  `cookie`, `session`, `authorization`, `api_key`, `credential`, `otp` — whatever it holds, at any
  depth of the payload.
- **The body of a request** — no quiz content, no wiki page, no form payload.
- **Settings values** — `settings_changed` names the keys, never their values, so the collector
  token cannot be read back from the SIEM.

## The event, as a collector sees it

```json
{
  "schema": "openlearn.audit/1",
  "ts": "2026-11-12T08:16:41.600Z",
  "event": "quiz_deleted",
  "outcome": "success",
  "source": "content",
  "ip": "203.0.113.24",
  "actor": { "id": 7, "email": "author@example.org", "role": "user" },
  "target": { "type": "quiz", "id": "128", "name": "Une étoile pour le Père Noël" },
  "detail": { "note": "deleted with 13 scenes" }
}
```

`source` is one of `api`, `content`, `admin` or `ai`. Fields are bounded (300 characters), stripped
of control characters, and a batch never mixes more than 50 events.

## Transport 1 — syslog

RFC 5424, one datagram or one line per event, with the interesting fields repeated in the
structured data so a rule matches without parsing JSON:

```
<110>1 2026-11-12T08:16:41.600Z openlearn.example.org openlearn - quiz_deleted
[openlearn@32473 event="quiz_deleted" outcome="success" actor="7"
actor_email="author@example.org" target_type="quiz" target_id="128" ip="203.0.113.24"]
{"schema":"openlearn.audit/1", ...}
```

- **Priority**: facility × 8 + severity. Default facility is 13 (*log audit*); severity is 6
  (*informational*) for a success and 4 (*warning*) for a failure. A rule can therefore filter on
  `severity` alone.
- **Protocols**: `udp`, `tcp`, `tls`. TLS uses the system trust store; verification can be turned
  off for a collector with a self-signed certificate, which is a deliberate, visible choice.
- **Hostname**: whatever the administrator sets (`log.syslog_hostname`), or `openlearn`.

## Transport 2 — HTTP POST

One request per batch, `Content-Type: application/json`:

```json
{ "source": "openlearn", "schema": "openlearn.audit/1", "events": [ { … }, { … } ] }
```

If a token is set, it is sent as `Authorization: Bearer <token>` — never in the URL, never in the
body. The URL must be `http://` or `https://`: `file://` and other schemes are refused when the
setting is saved, so a misconfiguration cannot make the server read a local file.

Syslog and HTTP are delivered **independently**: one can be down while the other keeps working, and
the test button reports each one separately.

## Configuration

In **Administration → Settings → Audit forwarding**, or in the environment (settings stored in the
database take precedence, and can be changed without a restart):

| Variable | Default | Purpose |
| --- | --- | --- |
| `OL_LOG_ENABLED` | `false` | Master switch. No target, no output. |
| `OL_LOG_SYSLOG_HOST` | empty | Collector hostname or IP. |
| `OL_LOG_SYSLOG_PORT` | `514` | UDP/TCP/TLS port. |
| `OL_LOG_SYSLOG_PROTOCOL` | `udp` | `udp`, `tcp` or `tls`. |
| `OL_LOG_SYSLOG_FACILITY` | `13` | Syslog facility, 0–23. |
| `OL_LOG_SYSLOG_HOSTNAME` | empty | Hostname announced in the header. |
| `OL_LOG_SYSLOG_TLS_VERIFY` | `true` | Verify the collector certificate. |
| `OL_LOG_HTTP_URL` | empty | Collector endpoint, `http(s)` only. |
| `OL_LOG_HTTP_TOKEN` | empty | Bearer token, write-only. |
| `OL_LOG_HTTP_VERIFY_TLS` | `true` | Verify the endpoint certificate. |
| `OL_LOG_HTTP_TIMEOUT_SECONDS` | `5` | Delivery timeout, 1–60. |

**Send a test event** delivers one synthetic event synchronously and reports the collector's answer
per target (`syslog: ok · http: ok`). Do it right after configuring: a wiring problem found in
daylight costs a minute, the same problem found during an incident costs the incident.

## Collector recipes

**Splunk** — add a UDP or TCP data input (port 514 or a dedicated one), `sourcetype=openlearn:audit`,
then extract the JSON message and filter on the structured data:

```
index=security sourcetype=openlearn:audit event=login_failure
| stats count by actor_email ip
```

Splunk's HTTP Event Collector expects its own envelope (`{"event": …}` per request). If you prefer
HTTP, point `log.http_url` at a three-line relay rather than changing the product:

```python
# POST /openlearn  ->  POST https://splunk:8088/services/collector/event
import json, os, httpx
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/openlearn")
async def relay(request: Request) -> dict:
    for event in (await request.json())["events"]:
        httpx.post(
            os.environ["HEC_URL"],
            json={"event": event, "sourcetype": "openlearn:audit", "index": "security"},
            headers={"Authorization": f"Splunk {os.environ['HEC_TOKEN']}"},
            timeout=5,
        )
    return {"ok": True}
```

**Microsoft Sentinel** — the Logs Ingestion API takes a JSON array, so a relay of the same size maps
our batch to the data collection rule endpoint (`/dataCollectionRules/<dcr>/streams/<stream>?
api-version=2023-01-01`), with an Entra ID token instead of the HEC token. Syslog is also accepted
through the Azure Monitor Agent if you already run it.

**Google SecOps** — point a forwarder at the syslog port; the JSON message is parsed by a parser
extension on `openlearn@32473.event`, `actor_email` and `target_type`.

**Sekoia** — syslog intake as well, or an HTTP intake that accepts a JSON array. Same fields.

**Any rsyslog or syslog-ng** — the RFC 5424 header is standard, so a plain `*.* @siem:514` rule
collects the events without any parser at all.

## What the tests guarantee

`tests/test_log_forwarding.py` runs a real HTTP collector and a real UDP socket, so these are
measured, not asserted in prose:

| Property | Test |
| --- | --- |
| Nothing leaves while the switch is off, or with no target | `test_a_disabled_forwarder_sends_nothing`, `test_a_target_without_the_switch_stays_silent` |
| A login really arrives, with actor, address and timestamp | `test_a_login_arrives_as_one_json_event` |
| The bearer token travels in the header, never in the body | `test_the_collector_receives_the_bearer_token_and_not_in_the_body` |
| Syslog is valid RFC 5424, with the priority computed from facility and severity | `test_syslog_carries_rfc5424_with_structured_data` |
| Both transports are served in the same run | `test_both_targets_are_served` |
| No field named like a secret is forwarded, at any depth | `test_no_field_named_like_a_secret_is_forwarded` |
| The settings API masks the token | `test_the_settings_api_masks_the_collector_token` |
| A settings change forwards key names only | `test_changing_a_setting_forwards_the_key_names_only` |
| A newline in a title cannot forge a second syslog record | `test_a_newline_in_content_cannot_forge_a_second_syslog_record` |
| A full queue drops the event instead of growing | `test_a_full_queue_drops_the_event_instead_of_growing` |
| A dead collector neither fails nor slows the request | `test_a_dead_collector_does_not_fail_the_login` |
| A broken syslog target does not silence HTTP | `test_a_broken_syslog_target_does_not_silence_the_http_one` |
| `file://` and other schemes are refused, as are out-of-range ports and facilities | `test_a_target_that_makes_no_sense_is_refused` |
| Only an administrator reads the status or sends a test event | `test_only_an_administrator_reads_or_tests_the_forwarder`, `test_a_visitor_cannot_read_the_status` |
| The test button reports each target and leaves a local trace | `test_the_test_endpoint_proves_each_target_and_leaves_a_trace` |
| Content lifecycle events carry the name of the item | `test_creating_and_deleting_content_is_forwarded_with_its_name` |
| An AI call is forwarded without its prompt | `test_an_ai_call_is_forwarded_without_the_prompt` |

## When nothing arrives

**Administration → Settings → Audit forwarding → Send a test event** is the first answer: it reports
the collector's own answer, per target, immediately.

For the counters, `GET /api/v1/admin/log/status` (administrator only) returns:

```json
{ "configured": true, "targets": { "syslog": false, "http": true }, "pending": 0,
  "sent": 1284, "dropped": 0, "failed": 0, "paused_seconds": 0,
  "last_error": "", "last_sent_at": "2026-11-12T08:16:41.600Z" }
```

- `dropped` growing while `failed` grows too: the collector refuses or is unreachable —
  `last_error` names it.
- `paused_seconds` above zero: after five consecutive failures the sender backs off (30 s, doubling
  to 5 minutes). A collector that is down must not become a load amplifier.
- `sent` growing, `last_sent_at` moving, but nothing at the collector: the target is right and the
  *collector's* input is wrong — check its port, its certificate, its index.

Events dropped during an outage are gone on purpose: the queue is bounded (2 000 events) and never
becomes an unbounded memory leak. The local `security_events` trail keeps what the collector missed.
