"""The demo package must pair each questionnaire with the wiki it illustrates."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.db import SessionLocal
from app.demo.seed import _load, content_files
from app.models import Quiz, Wiki, WikiQuizLink


def _pairing_entries() -> list[tuple[str, dict]]:
    pairs = []
    for path in content_files():
        document = _load(path)
        if (document.get("kind") or path.stem) != "quizzes":
            continue
        for entry in document.get("items") or []:
            if entry.get("wiki") or entry.get("wiki_title"):
                pairs.append((path.name, entry))
    return pairs


def test_every_questionnaire_names_the_wiki_it_was_written_for():
    pairs = _pairing_entries()
    assert len(pairs) >= 10, "the package ships questionnaires for the demo wikis"
    for where, entry in pairs:
        target = entry.get("wiki") or entry.get("wiki_title")
        assert isinstance(target, str) and target.strip(), f"{where}: empty wiki target"
        assert entry.get("questions"), f"{where}: a paired questionnaire needs questions"


def test_the_paired_questionnaires_cover_both_languages_and_modes():
    entries = [entry for _, entry in _pairing_entries()]
    assert {"fr", "de", "es", "en"} <= {entry["default_language"] for entry in entries}
    assert {"qcm", "swipe", "poll"} <= {entry["mode"] for entry in entries}
    # A pair the reader can actually reach: every language of the interface
    # is not required, but each questionnaire must be readable in four.
    for entry in entries:
        languages = {entry["default_language"], *entry.get("title_translations", {})}
        assert len(languages) == 4, f"{entry['title']!r} is not fully translated"


def test_seeding_attaches_the_questionnaires_to_their_wikis(client):
    from app.demo.seed import seed_showcase

    seed_showcase(force=True)

    with SessionLocal() as db:
        links = db.execute(
            select(Wiki.slug, Quiz.title)
            .join(WikiQuizLink, WikiQuizLink.wiki_id == Wiki.id)
            .join(Quiz, Quiz.id == WikiQuizLink.quiz_id)
        ).all()
        shipped = {
            slug for (slug,) in db.execute(select(Wiki.slug)).all()
        }

    assert len(links) >= 10, "each shipped wiki with a questionnaire is linked"
    assert len({slug for slug, _ in links}) >= 7, "the pairs spread across the catalogue"
    assert all(slug in shipped for slug, _ in links)

    with SessionLocal() as db:
        wiki_id = db.scalar(select(Wiki.id).where(Wiki.slug == "demo-how-the-internet-works"))
    assert wiki_id is not None
    response = client.get(f"/api/v1/wiki/{wiki_id}/quizzes")
    assert response.status_code == 200, response.text
    titles = [item["title"] for item in response.json()["items"]]
    assert any("Internet" in title for title in titles), titles


def test_seeding_twice_does_not_duplicate_a_link(client):
    from app.demo.seed import seed_showcase

    seed_showcase(force=True)
    with SessionLocal() as db:
        first = db.scalar(select(WikiQuizLink).limit(1))
        first_id = first.id if first else None
    seed_showcase(force=True)
    with SessionLocal() as db:
        rows = db.execute(
            select(WikiQuizLink.wiki_id, WikiQuizLink.quiz_id, WikiQuizLink.id)
        ).all()
    keys = [(wiki_id, quiz_id) for wiki_id, quiz_id, _ in rows]
    assert len(keys) == len(set(keys)), "a pair is never attached twice"
    assert first_id in {link_id for *_, link_id in rows}


def test_a_questionnaire_naming_an_absent_wiki_is_skipped_not_fatal():
    """The DNS primer and the riding capsule are created by hand on an instance."""
    payload = json.loads(
        json.dumps(
            {
                "title": "Sonde de couplage",
                "description": "",
                "mode": "qcm",
                "wrong_answer_policy": "penalty",
                "default_language": "fr",
                "is_multilingual": False,
                "timer_mode": "per_question",
                "wiki_title": "Un wiki qui n'existe pas",
                "questions": [
                    {
                        "text_html": "<p>Question ?</p>",
                        "time_limit_seconds": 20,
                        "points": 100,
                        "options": [
                            {"text": "Oui", "is_correct": True},
                            {"text": "Non", "is_correct": False},
                        ],
                    }
                ],
            }
        )
    )
    from app.db import SessionLocal
    from app.demo.seed import _author, _install_quiz

    with SessionLocal() as db:
        author = _author(db, "curator@example.com", "OpenLearn Curator")
        assert _install_quiz(db, author, payload) is not None
        db.commit()
        assert db.scalar(select(Quiz).where(Quiz.title == "Sonde de couplage")) is not None
        assert db.scalar(select(WikiQuizLink).join(Quiz).where(Quiz.title == "Sonde de couplage")) is None
