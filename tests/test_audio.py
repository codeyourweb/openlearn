# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Speech transcripts: the script, the cache, the ceiling, and who may ask.

The synthesiser is replaced by a fake that answers instantly: what these tests
pin down is everything around it — what is read aloud, what is never paid for
twice, and what a visitor is allowed to hear.
"""

from __future__ import annotations

import pytest

from app import audio
from app.config import settings
from tests.conftest import csrf_headers, register_user

FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 512


@pytest.fixture()
def tts(monkeypatch):
    """Turn the feature on and record every synthesis request."""
    calls: list[tuple[str, str, str, str]] = []

    def fake_speak(text: str, language: str, voice: str, tone: str = "neutral") -> tuple[bytes, float]:
        calls.append((text, language, voice, tone))
        return FAKE_MP3, round(len(text) / 15.4, 2)

    monkeypatch.setattr(audio, "_speak", fake_speak)
    monkeypatch.setattr(settings, "audio_enabled", True)
    monkeypatch.setattr(settings, "audio_service_url", "http://tts.example/v1")
    monkeypatch.setattr(settings, "audio_max_chars", 12000)
    monkeypatch.setattr(settings, "audio_chunk_chars", 900)
    return calls


def _wiki_with_page(client, content="# Le DNS\n\nUn résolveur cache les réponses. Il les garde un moment."):
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Manuel réseau", "description": "", "default_language": "fr"},
        headers=csrf_headers(client),
    ).json()
    page = client.post(
        f"/api/v1/wiki/{wiki['id']}/pages",
        json={"title": "Bases du DNS", "content_md": content},
        headers=csrf_headers(client),
    )
    assert page.status_code == 201, page.text
    return wiki, page.json()


def _quiz(client):
    quiz = client.post(
        "/api/v1/quizzes",
        json={
            "title": "Sécurité réseau",
            "description": "Les bases.",
            "wrong_answer_policy": "zero",
            "is_public": True,
            "questions": [
                {
                    "text_html": "<p>Que fait un pare-feu ?</p>",
                    "options": [
                        {"text": "Il filtre le trafic", "is_correct": True},
                        {"text": "Il décore la salle", "is_correct": False},
                    ],
                }
            ],
        },
        headers=csrf_headers(client),
    )
    assert quiz.status_code == 201, quiz.text
    return quiz.json()


# ---------------------------------------------------------------------------
# What is read aloud
# ---------------------------------------------------------------------------


def test_a_heading_becomes_a_sentence_a_list_keeps_its_items():
    paragraphs = audio.markdown_to_speech("# Le cheval\n\n- Sangle\n- Frontal")
    assert paragraphs == ["Le cheval.", "Sangle", "Frontal"]


def test_code_tables_and_images_are_not_read_aloud():
    markdown = (
        "Un texte utile.\n\n"
        "```\nne pas lire\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "![photo](x.png) Fin.\n"
    )
    spoken = " ".join(audio.markdown_to_speech(markdown))
    assert "ne pas lire" not in spoken
    assert "photo" not in spoken
    assert "|" not in spoken
    assert "Un texte utile" in spoken


def test_links_are_read_as_their_text_never_as_their_address():
    spoken = " ".join(audio.markdown_to_speech("Voir [le guide](https://exemple.fr/tres/long/chemin)."))
    assert "guide" in spoken
    assert "exemple.fr" not in spoken


def test_no_chunk_exceeds_the_limit():
    paragraphs = ["Une phrase courte. " * 200]
    chunks = audio.chunk(paragraphs, 300)
    assert chunks
    assert max(len(c) for c in chunks) <= 300
    # Nothing is lost in the cutting.
    assert sum(len(c) for c in chunks) >= len(paragraphs[0].strip()) - len(chunks)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


def test_an_instance_without_a_service_offers_no_audio(client):
    response = client.get("/api/v1/audio/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["languages"] == []


def test_the_status_names_the_nine_languages_and_not_the_three_it_lacks(client, tts):
    payload = client.get("/api/v1/audio/status").json()
    assert payload["enabled"] is True
    assert set(payload["languages"]) == {"en", "fr", "de", "es", "it", "pt", "ru", "zh", "ja"}
    for missing in ("hi", "bn", "ar"):
        assert missing not in payload["languages"]


def test_the_feature_can_be_switched_off_from_the_environment(client, tts, monkeypatch):
    register_user(client, "author@example.com")
    monkeypatch.setattr(settings, "audio_enabled", False)
    assert client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": 1, "voice": "female"},
        headers=csrf_headers(client),
    ).status_code == 503


# ---------------------------------------------------------------------------
# Generation, cache and staleness
# ---------------------------------------------------------------------------


def test_a_page_is_transcribed_once_and_then_served(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)

    started = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["segments"] >= 1
    assert body["cpu_seconds"] > 0

    job = client.get(f"/api/v1/audio/jobs/{body['job_id']}").json()
    assert job["status"] == "done", job

    listed = client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()
    assert listed["enabled"] is True
    assert len(listed["renditions"]) == 1
    rendition = listed["renditions"][0]
    assert rendition["voice"] == "female"
    assert rendition["language"] == "fr"
    assert len(rendition["segments"]) == body["segments"]
    assert all(segment["path"].startswith("/media/") for segment in rendition["segments"])
    assert all(segment["path"].endswith(".mp3") for segment in rendition["segments"])


def test_asking_twice_pays_nothing_the_second_time(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    payload = {"owner_type": "page", "owner_id": page["id"], "voice": "female"}

    client.post("/api/v1/audio/render", json=payload, headers=csrf_headers(client))
    first = len(tts)

    second = client.post("/api/v1/audio/render", json=payload, headers=csrf_headers(client))
    assert second.status_code == 202
    assert len(tts) == first, "unchanged text must not be synthesised again"


def test_editing_one_sentence_re_synthesises_only_that_sentence(client, tts):
    register_user(client, "author@example.com")
    wiki, page = _wiki_with_page(client)
    payload = {"owner_type": "page", "owner_id": page["id"], "voice": "female"}
    client.post("/api/v1/audio/render", json=payload, headers=csrf_headers(client))
    before = len(tts)

    saved = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": "Bases du DNS", "content_md": "# Le DNS\n\nUn résolveur cache les réponses. Il les garde longtemps.", "tags": [], "note": ""},
        headers=csrf_headers(client),
    )
    assert saved.status_code == 200, saved.text
    client.post("/api/v1/audio/render", json=payload, headers=csrf_headers(client))
    assert len(tts) == before + 1


def test_an_edited_page_no_longer_plays_its_old_transcript(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    saved = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": "Bases du DNS", "content_md": "# Autre chose\n\nLe texte a changé.", "tags": [], "note": ""},
        headers=csrf_headers(client),
    )
    assert saved.status_code == 200, saved.text
    listed = client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()
    assert listed["renditions"] == []


def test_a_plain_questionnaire_cannot_be_read_aloud(client, tts):
    """Only a wiki page and an adventure scene carry a transcript."""
    register_user(client, "author@example.com")
    quiz = _quiz(client)
    refused = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "quiz", "owner_id": quiz["id"], "voice": "male"},
        headers=csrf_headers(client),
    )
    assert refused.status_code == 422, refused.text
    assert "page or node" in refused.json()["detail"]


def test_the_two_voices_are_synthesised_separately(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    for voice in ("female", "male"):
        response = client.post(
            "/api/v1/audio/render",
            json={"owner_type": "page", "owner_id": page["id"], "voice": voice},
            headers=csrf_headers(client),
        )
        assert response.status_code == 202, response.text
    assert {call[2] for call in tts} == {"female", "male"}
    # The engine names are two settings, so an instance can swap engines without
    # touching the code.
    assert audio.voice_name("female") == settings.audio_voice_female
    assert audio.voice_name("male") == settings.audio_voice_male
    listed = client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()
    assert {row["voice"] for row in listed["renditions"]} == {"female", "male"}


# ---------------------------------------------------------------------------
# Limits, refusals and permissions
# ---------------------------------------------------------------------------


def test_a_language_the_engine_cannot_speak_is_refused_with_the_list(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    response = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female", "language": "hi"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
    assert "hi" not in response.json()["detail"]["languages"]


def test_a_document_above_the_ceiling_is_refused_before_any_work(client, tts, monkeypatch):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client, content="Une phrase. " * 200)
    monkeypatch.setattr(settings, "audio_max_chars", 100)
    response = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
    assert tts == [], "a refused request must not reach the engine"


def test_a_stranger_cannot_ask_for_a_transcript(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    register_user(client, "intruder@example.com", display_name="Intruder")
    response = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    assert response.status_code in (403, 404)


def test_a_transcript_of_a_draft_page_is_not_served_to_a_visitor(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    client.cookies.clear()
    listed = client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()
    assert listed["renditions"] == []


def test_an_unknown_voice_is_refused(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    response = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "robot"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422


def test_the_transcript_can_be_removed_by_its_author(client, tts):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)
    client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    rendition = client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()["renditions"][0]
    removed = client.delete(f"/api/v1/audio/renditions/{rendition['id']}", headers=csrf_headers(client))
    assert removed.status_code == 204
    assert client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()["renditions"] == []


# ---------------------------------------------------------------------------
# The engine answers nonsense
# ---------------------------------------------------------------------------


def test_an_html_error_page_is_not_stored_as_audio(client, monkeypatch):
    class BrokenClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url, json):  # noqa: A002 - mirroring httpx
            class Response:
                status_code = 200
                content = b"<html>Gateway error</html>"
                headers: dict[str, str] = {}
                text = "<html>Gateway error</html>"

            return Response()

    monkeypatch.setattr(audio.httpx, "Client", BrokenClient)
    with pytest.raises(audio.AudioUnavailable):
        audio._speak("Bonjour", "fr", "female")


def test_a_service_that_answers_with_an_error_fails_the_job(client, tts, monkeypatch):
    register_user(client, "author@example.com")
    _, page = _wiki_with_page(client)

    def exploding(text, language, voice, tone="neutral"):
        raise audio.AudioUnavailable("The speech service is unreachable: ConnectError")

    monkeypatch.setattr(audio, "_speak", exploding)
    started = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    job = client.get(f"/api/v1/audio/jobs/{started.json()['job_id']}").json()
    assert job["status"] == "error"
    assert "unreachable" in job["error"]
    assert client.get(f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}").json()["renditions"] == []


# ---------------------------------------------------------------------------
# Intonation, and what removing a transcript really removes
# ---------------------------------------------------------------------------


def test_the_same_text_can_be_read_in_two_tones(client, tts):
    """A warmer reading is a second recording, not the neutral one replayed."""
    register_user(client, "tones@example.com")
    _, page = _wiki_with_page(client)
    for tone in ("neutral", "warm"):
        answer = client.post(
            "/api/v1/audio/render",
            json={"owner_type": "page", "owner_id": page["id"], "voice": "female", "tone": tone},
            headers=csrf_headers(client),
        )
        assert answer.status_code == 202, answer.text

    tones = [call[3] for call in tts]
    assert "neutral" in tones and "warm" in tones
    # Two readings of the same sentence: the cache key must tell them apart.
    neutral_texts = [call[0] for call in tts if call[3] == "neutral"]
    warm_texts = [call[0] for call in tts if call[3] == "warm"]
    assert set(neutral_texts) == set(warm_texts)

    renditions = client.get(
        f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}"
    ).json()["renditions"]
    assert {row["tone"] for row in renditions} == {"neutral", "warm"}


def test_an_unknown_tone_is_refused(client, tts):
    register_user(client, "tone@example.com")
    _, page = _wiki_with_page(client)
    answer = client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": page["id"], "tone": "shouted"},
        headers=csrf_headers(client),
    )
    assert answer.status_code == 422
    assert tts == []


def test_a_removed_transcript_is_really_synthesised_again(client, tts):
    """Removing a transcript used to leave the cached segments in place.

    The next request then answered from the cache in a fraction of a second: the
    interface said "ready" and the reader got the recording they had just
    deleted. Deleting frees the segments, so asking again costs real synthesis.
    """
    register_user(client, "purge@example.com")
    _, page = _wiki_with_page(client)
    body = {"owner_type": "page", "owner_id": page["id"], "voice": "female", "tone": "formal"}
    client.post("/api/v1/audio/render", json=body, headers=csrf_headers(client))
    first_pass = len(tts)
    assert first_pass > 0

    rendition = client.get(
        f"/api/v1/audio/renditions?owner_type=page&owner_id={page['id']}"
    ).json()["renditions"][0]
    assert client.delete(
        f"/api/v1/audio/renditions/{rendition['id']}", headers=csrf_headers(client)
    ).status_code == 204

    client.post("/api/v1/audio/render", json=body, headers=csrf_headers(client))
    assert len(tts) > first_pass, "the second request was served from the removed cache"


def test_a_segment_another_page_still_uses_survives_the_deletion(client, tts):
    """Two pages may share a sentence: removing one must not silence the other."""
    register_user(client, "shared@example.com")
    sentence = "# Le DNS\n\nUn resolveur cache les reponses."
    _, first = _wiki_with_page(client, sentence)
    _, second = _wiki_with_page(client, sentence)
    for page in (first, second):
        client.post(
            "/api/v1/audio/render",
            json={"owner_type": "page", "owner_id": page["id"], "voice": "female"},
            headers=csrf_headers(client),
        )
    paid = len(tts)
    assert paid > 0, "nothing was synthesised"

    rendition = client.get(
        f"/api/v1/audio/renditions?owner_type=page&owner_id={first['id']}"
    ).json()["renditions"][0]
    client.delete(f"/api/v1/audio/renditions/{rendition['id']}", headers=csrf_headers(client))

    # The other page still plays: its segment was kept.
    still_there = client.get(
        f"/api/v1/audio/renditions?owner_type=page&owner_id={second['id']}"
    ).json()["renditions"]
    assert still_there
    client.post(
        "/api/v1/audio/render",
        json={"owner_type": "page", "owner_id": second["id"], "voice": "female"},
        headers=csrf_headers(client),
    )
    assert len(tts) == paid, "a shared segment was paid for again"
