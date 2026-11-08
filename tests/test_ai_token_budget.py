# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""A reasoning model spends its budget thinking and answers with nothing.

Every provider call used to fail with "AI unavailable" in that case, and the
admin self-test reported a successful call with an empty answer. Both now cope:
the call retries once with more room, and the self-test shows what came back.
"""

from __future__ import annotations

import httpx
import pytest

from app import ai as ai_module
from app.config import settings
from tests.conftest import csrf_headers, register_user


@pytest.fixture()
def provider(monkeypatch):
    """Enable AI and let a test script the provider's answers."""
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_model", "fake-model")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake-provider/v1")
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "search_base_url", "")

    class Response:
        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.status_code = 200
            self.text = str(payload)

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class Client:
        def __init__(self, answers: list[dict], calls: list[int]) -> None:
            self.answers = answers
            self.calls = calls

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def post(self, _url: str, json: dict | None = None, headers: dict | None = None) -> Response:
            self.calls.append((json or {}).get("max_tokens"))
            return Response(self.answers[min(len(self.calls) - 1, len(self.answers) - 1)])

    def install(answers: list[dict]) -> list[int]:
        calls: list[int] = []
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: Client(answers, calls))
        return calls

    install.calls_for = install  # type: ignore[attr-defined]
    return install


def _answer(content: str | None, finish: str = "stop", reasoning: str | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message, "finish_reason": finish}]}


def test_an_answer_cut_off_by_the_budget_is_asked_again_with_more_room(client, provider):
    calls = provider([_answer("", "length", "thinking"), _answer("pong")])

    assert ai_module._chat([{"role": "user", "content": "ping"}], max_tokens=8) == "pong"
    assert len(calls) == 2
    assert calls[1] > calls[0], f"the retry did not give the model more room: {calls}"


def test_a_retry_is_not_granted_forever(client, provider):
    calls = provider([_answer("", "length", "thinking")])

    with pytest.raises(ai_module.AiError):
        ai_module._chat([{"role": "user", "content": "ping"}], max_tokens=8)
    assert len(calls) == 2, f"expected exactly one retry, saw {len(calls)} calls"


def test_an_empty_answer_that_was_not_truncated_fails_at_once(client, provider):
    calls = provider([_answer("   ")])

    with pytest.raises(ai_module.AiError):
        ai_module._chat([{"role": "user", "content": "ping"}], max_tokens=8)
    assert len(calls) == 1, f"a blank answer must not be retried: {calls}"


def test_a_healthy_answer_costs_one_call(client, provider):
    calls = provider([_answer("pong")])

    assert ai_module._chat([{"role": "user", "content": "ping"}]) == "pong"
    assert len(calls) == 1


def test_the_admin_self_test_shows_a_reasoning_models_answer(client, provider):
    """The button used to say "ok" with an empty string beside it."""
    register_user(client)
    from tests.conftest import make_admin

    make_admin(client)
    provider([_answer("", "length", reasoning="pong")])

    response = client.post("/api/v1/admin/settings/ai/test", json={}, headers=csrf_headers(client))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["answer"] == "pong", body
