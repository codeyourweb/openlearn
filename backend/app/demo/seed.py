"""Demo mode: install a showcase catalogue into an empty instance.

Demo content is data, not code: the JSON files under ``demo/content`` describe
wikis, questionnaires, decks and stories, and this package turns them into rows
through the same validation the API uses. A private deployment never loads any
of it — ``OL_DEMO_MODE`` is off and nothing here runs.

Install it into an existing database with::

    python -m app.demo.seed          # inside the container, or ./scripts/demo-seed.sh
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..config import settings
from ..content import compute_content_hash
from ..db import SessionLocal
from ..models import (
    AppSetting,
    Option,
    Question,
    Quiz,
    RevisionCard,
    RevisionDeck,
    User,
    Wiki,
    WikiPage,
    utcnow,
)
from ..schemas import QuizIn
from ..security import hash_password

logger = logging.getLogger("openlearn.demo")

CONTENT_VERSION_KEY = "demo.content_version"


def _content_dir() -> Path:
    return Path(settings.demo_content_dir) / "content"


def content_files() -> list[Path]:
    directory = _content_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def content_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in content_files():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:32]


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:  # pragma: no cover - authoring error
        raise SystemExit(f"{path.name}: invalid JSON ({exc})") from exc


def _author(db, email: str, display_name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    user = User(
        email=email,
        password_hash=hash_password(settings.admin_password or "DemoPassw0rd!"),
        display_name=display_name,
        is_active=True,
        is_trusted=True,
    )
    db.add(user)
    db.flush()
    return user


def _install_wikis(db, author: User, entries: list[dict[str, Any]]) -> int:
    created = 0
    for entry in entries:
        slug = entry["slug"]
        if db.scalar(select(Wiki.id).where(Wiki.slug == slug)) is not None:
            continue
        wiki = Wiki(
            owner_id=author.id,
            title=entry["title"],
            slug=slug,
            description=entry.get("description", ""),
            status="public",
            is_public=True,
            default_language=entry.get("language", "en"),
            published_at=utcnow(),
        )
        db.add(wiki)
        db.flush()
        parent_by_key: dict[str, WikiPage] = {}
        for position, page_entry in enumerate(entry.get("pages", [])):
            page = WikiPage(
                wiki_id=wiki.id,
                slug=page_entry["slug"],
                title=page_entry["title"],
                content_md=page_entry.get("markdown", ""),
                tags=page_entry.get("tags", []),
                position=position,
                author_id=author.id,
                current_version_number=1,
            )
            db.add(page)
            db.flush()
            parent_key = page_entry.get("parent")
            if parent_key and parent_key in parent_by_key:
                page.parent_id = parent_by_key[parent_key].id
            parent_by_key[page_entry["slug"]] = page
        created += 1
    return created


def _install_quiz(db, author: User, entry: dict[str, Any], *, status: str = "public") -> Quiz | None:
    existing = db.scalar(select(Quiz.id).where(Quiz.title == entry["title"]))
    if existing is not None:
        return None
    payload = QuizIn(**entry)
    # `title` is NOT NULL: it has to exist before the first flush, otherwise the
    # row is rejected before `_apply_quiz` ever runs.
    quiz = Quiz(
        owner_id=author.id,
        title=payload.title,
        description=payload.description or "",
        mode=payload.mode,
        status="draft",
        is_public=False,
    )
    db.add(quiz)
    db.flush()
    from ..routers.quizzes import _apply_quiz

    _apply_quiz(db, quiz, payload)
    quiz.status = status
    quiz.is_public = status == "public"
    quiz.default_language = payload.default_language
    quiz.languages = sorted({payload.default_language, *payload.title_translations})
    quiz.published_at = utcnow() if status == "public" else None
    quiz.content_hash = compute_content_hash(quiz)
    db.flush()
    if status == "public":
        from ..versions import freeze

        version = freeze(db, quiz, user=author, publish=True, auto_publish=True, note="Demo content")
        db.add(version)
        quiz.published_version_number = version.number
    return quiz


def _install_deck(db, author: User, entry: dict[str, Any]) -> int:
    if db.scalar(select(RevisionDeck.id).where(RevisionDeck.title == entry["title"])) is not None:
        return 0
    deck = RevisionDeck(
        owner_id=author.id,
        title=entry["title"],
        description=entry.get("description", ""),
        is_public=True,
        aspect=entry.get("aspect", "2:3"),
    )
    db.add(deck)
    db.flush()
    for position, card in enumerate(entry.get("cards", [])):
        db.add(
            RevisionCard(
                deck_id=deck.id,
                position=position,
                front_md=card.get("front", ""),
                back_md=card.get("back", ""),
                source="manual",
            )
        )
    return 1


def seed_showcase(*, force: bool = False) -> dict[str, int]:
    """Install the showcase once. Returns what was created."""
    if not settings.demo_mode and not force:
        return {"skipped": 1}
    files = content_files()
    if not files:
        logger.warning("Demo mode is on but no content was found in %s", _content_dir())
        return {"missing": 1}

    fingerprint = content_fingerprint()
    stats = {"wikis": 0, "quizzes": 0, "decks": 0, "adventures": 0}
    with SessionLocal() as db:
        marker = db.get(AppSetting, CONTENT_VERSION_KEY)
        if marker is not None and marker.value.strip('"') == fingerprint and not force:
            return {"unchanged": 1}
        author = _author(db, settings.admin_email or "curator@example.com", "OpenLearn Curator")

        for path in files:
            document = _load(path)
            kind = document.get("kind") or path.stem
            if kind == "wikis":
                stats["wikis"] += _install_wikis(db, author, document["items"])
            elif kind == "quizzes":
                for entry in document["items"]:
                    if _install_quiz(db, author, entry) is not None:
                        stats["quizzes"] += 1
            elif kind == "adventures":
                for entry in document["items"]:
                    if _install_quiz(db, author, entry) is not None:
                        stats["adventures"] += 1
            elif kind == "decks":
                for entry in document["items"]:
                    stats["decks"] += _install_deck(db, author, entry)
            else:
                logger.warning("%s: unknown content kind %r", path.name, kind)

        if marker is None:
            db.add(AppSetting(key=CONTENT_VERSION_KEY, value=json.dumps(fingerprint)))
        else:
            marker.value = json.dumps(fingerprint)
        db.commit()

        # The catalogue is written straight into the tables, so the search index
        # has to be rebuilt afterwards: otherwise a demo instance lists its
        # contents but finds none of them when someone searches.
        from ..search import ensure_index, ensure_wiki_index

        ensure_index(db)
        ensure_wiki_index(db)
    logger.info("Demo showcase installed: %s", stats)
    return stats


def validate_content() -> list[str]:
    """Parse every file and validate each payload; used by CI and the seeder."""
    problems: list[str] = []
    for path in content_files():
        document = _load(path)
        kind = document.get("kind") or path.stem
        items = document.get("items") or []
        if not isinstance(items, list):
            problems.append(f"{path.name}: 'items' must be a list")
            continue
        for index, entry in enumerate(items):
            where = f"{path.name}[{index}]"
            if kind in {"quizzes", "adventures"}:
                try:
                    QuizIn(**entry)
                except Exception as exc:  # pydantic ValidationError
                    problems.append(f"{where}: {exc}")
            elif kind == "wikis":
                for field in ("slug", "title", "pages"):
                    if field not in entry:
                        problems.append(f"{where}: missing {field}")
                for page in entry.get("pages", []):
                    for field in ("slug", "title"):
                        if field not in page:
                            problems.append(f"{where}: page missing {field}")
            elif kind == "decks":
                for field in ("title", "cards"):
                    if field not in entry:
                        problems.append(f"{where}: missing {field}")
    return problems


if __name__ == "__main__":  # pragma: no cover - operational entry point
    logging.basicConfig(level=logging.INFO)
    issues = validate_content()
    if issues:
        print("\n".join(issues))
        raise SystemExit(1)
    print(seed_showcase(force=True))
