# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Revision decks: a deck of cards, its cards, and the learner's three boxes.

Everything here is derived from content the platform already holds — a wiki
page, a questionnaire — so that a teacher never types forty cards by hand. A
card is a front, a back and an optional picture, and that is the whole model:
no per-domain code, no widget catalogue.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..cards import pairs_from_markdown, pairs_from_questionnaire
from ..cards_pdf import sheet_pdf
from ..config import settings
from ..deps import get_db, get_optional_user, require_user
from ..models import (
    Question,
    Quiz,
    RevisionCard,
    RevisionDeck,
    RevisionReview,
    User,
    Wiki,
    WikiMember,
    WikiPage,
    utcnow,
)

router = APIRouter(prefix="/api/v1/decks", tags=["revision cards"])

MAX_CARDS_PER_DECK = 300
MAX_TEXT = 4000

#: Portrait by default: a card that has to hold a picture loses half its face
#: when it is square, and every printed card the teachers sent us is 2:3.
ASPECTS = ("2:3", "3:4", "1:1", "3:2", "16:9")
DEFAULT_ASPECT = "2:3"


def _clean_aspect(value: str) -> str:
    if value not in ASPECTS:
        raise HTTPException(
            status_code=422, detail=f"Unknown card shape: {value} (expected one of {', '.join(ASPECTS)})."
        )
    return value


class DeckIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    wiki_id: int | None = None
    quiz_id: int | None = None
    is_public: bool = False
    aspect: str = DEFAULT_ASPECT


class DeckPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    is_public: bool | None = None
    aspect: str | None = None


class CardIn(BaseModel):
    # Empty is allowed: a picture can carry the front on its own. What is not
    # allowed is a card with neither words nor picture, checked below.
    front_md: str = Field(default="", max_length=MAX_TEXT)
    back_md: str = Field(default="", max_length=MAX_TEXT)
    image_path: str | None = Field(default=None, max_length=200)
    back_image_path: str | None = Field(default=None, max_length=200)


def _require_face(payload: CardIn) -> None:
    if not payload.front_md.strip() and not payload.image_path:
        raise HTTPException(
            status_code=422,
            detail="A card needs something on its front: a word, a sentence or a picture.",
        )


class ReorderIn(BaseModel):
    order: list[int] = Field(default_factory=list, max_length=MAX_CARDS_PER_DECK)


class ReviewIn(BaseModel):
    card_id: int
    known: bool


class FromSourceIn(BaseModel):
    page_id: int | None = None
    quiz_id: int | None = None
    title: str = Field(default="", max_length=160)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _readable(deck: RevisionDeck, user: User | None) -> bool:
    if deck.is_public:
        return True
    if user is None:
        return False
    return deck.owner_id == user.id or bool(user.is_staff)


def _writable(deck: RevisionDeck, user: User) -> bool:
    return deck.owner_id == user.id or bool(user.is_staff)


def _deck_or_404(db: OrmSession, deck_id: int, user: User | None) -> RevisionDeck:
    deck = db.get(RevisionDeck, deck_id)
    if deck is None or not _readable(deck, user):
        # A private deck must look missing, not forbidden.
        raise HTTPException(status_code=404, detail="Deck not found.")
    return deck


def _deck_for_write(db: OrmSession, deck_id: int, user: User) -> RevisionDeck:
    deck = _deck_or_404(db, deck_id, user)
    if not _writable(deck, user):
        raise HTTPException(status_code=403, detail="You cannot edit this deck.")
    return deck


def _wiki_readable(db: OrmSession, wiki: Wiki, user: User) -> bool:
    if wiki.status == "public" or wiki.owner_id == user.id or user.is_staff:
        return True
    member = db.scalar(
        select(WikiMember).where(WikiMember.wiki_id == wiki.id, WikiMember.user_id == user.id)
    )
    return member is not None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
def _serialise_card(card: RevisionCard, review: RevisionReview | None) -> dict:
    return {
        "id": card.id,
        "position": card.position,
        "front_md": card.front_md,
        "back_md": card.back_md,
        "image_path": card.image_path,
        "back_image_path": card.back_image_path,
        "source": card.source,
        "box": review.box if review else 0,
        "seen": review.seen if review else 0,
        "known": review.known if review else 0,
    }


def _serialise(
    deck: RevisionDeck,
    cards: list[dict],
    *,
    total: int | None = None,
    user: User | None = None,
) -> dict:
    return {
        "id": deck.id,
        "can_edit": bool(user is not None and _writable(deck, user)),
        "title": deck.title,
        "description": deck.description,
        "wiki_id": deck.wiki_id,
        "quiz_id": deck.quiz_id,
        "is_public": deck.is_public,
        "aspect": deck.aspect or DEFAULT_ASPECT,
        "owner_id": deck.owner_id,
        "card_count": total if total is not None else len(cards),
        "cards": cards,
        "created_at": deck.created_at.isoformat() if deck.created_at else None,
        "updated_at": deck.updated_at.isoformat() if deck.updated_at else None,
    }


def _cards_with_reviews(db: OrmSession, deck: RevisionDeck, user: User | None) -> list[dict]:
    cards = db.scalars(
        select(RevisionCard)
        .where(RevisionCard.deck_id == deck.id)
        .order_by(RevisionCard.position, RevisionCard.id)
    ).all()
    reviews: dict[int, RevisionReview] = {}
    if user is not None and cards:
        rows = db.scalars(
            select(RevisionReview).where(
                RevisionReview.user_id == user.id,
                RevisionReview.card_id.in_([card.id for card in cards]),
            )
        ).all()
        reviews = {row.card_id: row for row in rows}
    return [_serialise_card(card, reviews.get(card.id)) for card in cards]


def _next_position(db: OrmSession, deck_id: int) -> int:
    current = db.scalar(
        select(func.max(RevisionCard.position)).where(RevisionCard.deck_id == deck_id)
    )
    return (current or 0) + 1


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------
@router.get("", summary="List the decks you can read")
def list_decks(
    q: str = Query(default="", max_length=120),
    wiki_id: int | None = None,
    quiz_id: int | None = None,
    mine: bool = False,
    limit: int = Query(default=60, ge=1, le=120),
    offset: int = Query(default=0, ge=0),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
    response: Response = None,
) -> dict:
    query = select(RevisionDeck)
    if mine:
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to see your decks.")
        query = query.where(RevisionDeck.owner_id == user.id)
    elif user is None:
        query = query.where(RevisionDeck.is_public.is_(True))
    else:
        query = query.where(
            (RevisionDeck.is_public.is_(True)) | (RevisionDeck.owner_id == user.id)
        )
    if wiki_id is not None:
        query = query.where(RevisionDeck.wiki_id == wiki_id)
    if quiz_id is not None:
        query = query.where(RevisionDeck.quiz_id == quiz_id)
    if q:
        needle = f"%{q.strip().lower()}%"
        query = query.where(func.lower(RevisionDeck.title).like(needle))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    decks = db.scalars(
        query.order_by(RevisionDeck.updated_at.desc()).limit(limit).offset(offset)
    ).all()
    counts = dict(
        db.execute(
            select(RevisionCard.deck_id, func.count(RevisionCard.id))
            .where(RevisionCard.deck_id.in_([deck.id for deck in decks] or [-1]))
            .group_by(RevisionCard.deck_id)
        ).all()
    )
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return {
        "items": [
            _serialise(deck, [], total=counts.get(deck.id, 0)) for deck in decks
        ],
        "total": total,
    }


@router.get("/{deck_id}", summary="One deck with its cards")
def get_deck(
    deck_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    deck = _deck_or_404(db, deck_id, user)
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an empty deck")
def create_deck(
    payload: DeckIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    if payload.wiki_id is not None:
        wiki = db.get(Wiki, payload.wiki_id)
        if wiki is None or not _wiki_readable(db, wiki, user):
            raise HTTPException(status_code=404, detail="Wiki not found.")
    deck = RevisionDeck(
        owner_id=user.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        wiki_id=payload.wiki_id,
        quiz_id=payload.quiz_id,
        is_public=payload.is_public,
        aspect=_clean_aspect(payload.aspect),
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return _serialise(deck, [], user=user)


@router.put("/{deck_id}", summary="Rename, describe or publish a deck")
def update_deck(
    deck_id: int,
    payload: DeckPatch,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    if payload.aspect is not None:
        deck.aspect = _clean_aspect(payload.aspect)
    for field in ("title", "description", "is_public"):
        value = getattr(payload, field)
        if value is not None:
            setattr(deck, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(deck)
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a deck")
def delete_deck(
    deck_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    deck = _deck_for_write(db, deck_id, user)
    db.delete(deck)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
@router.post("/{deck_id}/cards", status_code=status.HTTP_201_CREATED, summary="Add a card")
def add_card(
    deck_id: int,
    payload: CardIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    _require_face(payload)
    count = db.scalar(
        select(func.count(RevisionCard.id)).where(RevisionCard.deck_id == deck.id)
    )
    if (count or 0) >= MAX_CARDS_PER_DECK:
        raise HTTPException(status_code=422, detail="This deck already holds too many cards.")
    card = RevisionCard(
        deck_id=deck.id,
        position=_next_position(db, deck.id),
        front_md=payload.front_md.strip(),
        back_md=payload.back_md.strip(),
        image_path=payload.image_path,
        back_image_path=payload.back_image_path,
        source="manual",
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _serialise_card(card, None)


@router.put("/{deck_id}/cards/{card_id}", summary="Edit a card")
def update_card(
    deck_id: int,
    card_id: int,
    payload: CardIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    card = db.get(RevisionCard, card_id)
    if card is None or card.deck_id != deck.id:
        raise HTTPException(status_code=404, detail="Card not found.")
    _require_face(payload)
    card.front_md = payload.front_md.strip()
    card.back_md = payload.back_md.strip()
    card.image_path = payload.image_path
    card.back_image_path = payload.back_image_path
    db.commit()
    db.refresh(card)
    return _serialise_card(card, None)


@router.delete(
    "/{deck_id}/cards/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a card",
)
def delete_card(
    deck_id: int,
    card_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    deck = _deck_for_write(db, deck_id, user)
    card = db.get(RevisionCard, card_id)
    if card is None or card.deck_id != deck.id:
        raise HTTPException(status_code=404, detail="Card not found.")
    db.delete(card)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{deck_id}/reorder", summary="Reorder the deck")
def reorder(
    deck_id: int,
    payload: ReorderIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    cards = {
        card.id: card
        for card in db.scalars(select(RevisionCard).where(RevisionCard.deck_id == deck.id)).all()
    }
    for index, card_id in enumerate(payload.order):
        card = cards.pop(card_id, None)
        if card is not None:
            card.position = index
    # Anything the client forgot keeps its relative order, at the end.
    for offset, card in enumerate(sorted(cards.values(), key=lambda row: row.position)):
        card.position = len(payload.order) + offset
    db.commit()
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user)


# ---------------------------------------------------------------------------
# Generating cards from what is already written
# ---------------------------------------------------------------------------
def _append_pairs(
    db: OrmSession,
    deck: RevisionDeck,
    pairs: list[tuple[str, str, str | None]],
    *,
    source: str = "wiki",
) -> int:
    existing = db.scalar(
        select(func.count(RevisionCard.id)).where(RevisionCard.deck_id == deck.id)
    ) or 0
    room = MAX_CARDS_PER_DECK - existing
    taken = {
        (card.front_md or "").strip().casefold()
        for card in db.scalars(
            select(RevisionCard).where(RevisionCard.deck_id == deck.id)
        ).all()
    }
    added = 0
    for front, back, image in pairs[: max(room, 0)]:
        key = front.strip().casefold()
        if not front.strip() or key in taken:
            continue
        taken.add(key)
        added += 1
        db.add(
            RevisionCard(
                deck_id=deck.id,
                position=_next_position(db, deck.id) + added,
                front_md=front.strip(),
                back_md=(back or "").strip(),
                image_path=image,
                source=source,
            )
        )
    return added


def _pairs_from_page(db: OrmSession, page: WikiPage) -> list[tuple[str, str, str | None]]:
    return [(front, back, None) for front, back in pairs_from_markdown(page.content_md)]


def _pairs_from_quiz(db: OrmSession, quiz: Quiz) -> list[tuple[str, str, str | None]]:
    questions = db.scalars(
        select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)
    ).all()
    return pairs_from_questionnaire(quiz, questions)


def _accessible_page(db: OrmSession, page_id: int, user: User) -> WikiPage:
    page = db.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    wiki = db.get(Wiki, page.wiki_id)
    if wiki is None or not _wiki_readable(db, wiki, user):
        raise HTTPException(status_code=404, detail="Page not found.")
    return page


def _accessible_quiz(db: OrmSession, quiz_id: int, user: User) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if not (quiz.is_public or quiz.owner_id == user.id or user.is_staff):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return quiz


@router.post(
    "/from-source",
    status_code=status.HTTP_201_CREATED,
    summary="Create a deck out of a wiki page or a questionnaire",
)
def from_source(
    payload: FromSourceIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    if payload.page_id is None and payload.quiz_id is None:
        raise HTTPException(status_code=422, detail="Give a page or a quiz.")
    wiki_id = quiz_id = None
    if payload.page_id is not None:
        page = _accessible_page(db, payload.page_id, user)
        pairs = _pairs_from_page(db, page)
        title = payload.title.strip() or page.title
        wiki_id = page.wiki_id
    else:
        quiz = _accessible_quiz(db, int(payload.quiz_id), user)
        pairs = _pairs_from_quiz(db, quiz)
        title = payload.title.strip() or quiz.title
        quiz_id = quiz.id
    if not pairs:
        raise HTTPException(
            status_code=422,
            detail="Nothing to make a card from here: add headings, or questions with an answer key.",
        )
    deck = RevisionDeck(
        owner_id=user.id,
        title=title[:160],
        description="",
        wiki_id=wiki_id,
        quiz_id=quiz_id,
        is_public=False,
    )
    db.add(deck)
    db.flush()
    added = _append_pairs(db, deck, pairs, source="quiz" if quiz_id else "wiki")
    db.commit()
    db.refresh(deck)
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user) | {"added": added}


@router.post("/{deck_id}/add-from-wiki", summary="Append the cards of a wiki page")
def add_from_wiki(
    deck_id: int,
    payload: FromSourceIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    if payload.page_id is None:
        raise HTTPException(status_code=422, detail="Give a page.")
    page = _accessible_page(db, payload.page_id, user)
    added = _append_pairs(db, deck, _pairs_from_page(db, page))
    db.commit()
    db.refresh(deck)
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user) | {"added": added}


@router.post("/{deck_id}/add-from-quiz", summary="Append the answer key of a questionnaire")
def add_from_quiz(
    deck_id: int,
    payload: FromSourceIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_for_write(db, deck_id, user)
    if payload.quiz_id is None:
        raise HTTPException(status_code=422, detail="Give a quiz.")
    quiz = _accessible_quiz(db, payload.quiz_id, user)
    added = _append_pairs(db, deck, _pairs_from_quiz(db, quiz), source="quiz")
    db.commit()
    db.refresh(deck)
    return _serialise(deck, _cards_with_reviews(db, deck, user), user=user) | {"added": added}


# ---------------------------------------------------------------------------
# Study
# ---------------------------------------------------------------------------
@router.get("/{deck_id}/study", summary="The cards, weakest first")
def study(
    deck_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    """Box 0 first, then the deck order.

    No shuffle: a teacher says "start with Léa" and the session must start with
    Léa. An unused `shuffle` flag used to sit in the signature and do nothing,
    which is worse than no flag at all.
    """
    deck = _deck_or_404(db, deck_id, user)
    cards = _cards_with_reviews(db, deck, user)
    cards.sort(key=lambda card: (card["box"], card["position"]))
    return _serialise(deck, cards)


@router.post("/{deck_id}/review", summary="Record what the learner thought of one card")
def review(
    deck_id: int,
    payload: ReviewIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    deck = _deck_or_404(db, deck_id, user)
    card = db.get(RevisionCard, payload.card_id)
    if card is None or card.deck_id != deck.id:
        raise HTTPException(status_code=404, detail="Card not found.")
    row = db.scalar(
        select(RevisionReview).where(
            RevisionReview.card_id == card.id, RevisionReview.user_id == user.id
        )
    )
    if row is None:
        row = RevisionReview(card_id=card.id, user_id=user.id, box=0, seen=0, known=0)
        db.add(row)
    row.seen += 1
    if payload.known:
        row.known += 1
        row.box = min(2, row.box + 1)
    else:
        row.box = 0
    row.updated_at = utcnow()
    db.commit()
    return {"card_id": card.id, "box": row.box, "seen": row.seen, "known": row.known}


@router.get("/{deck_id}/sheet.pdf", summary="Print the deck, eight cards per sheet")
def sheet(
    deck_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> Response:
    deck = _deck_or_404(db, deck_id, user)
    cards = db.scalars(
        select(RevisionCard)
        .where(RevisionCard.deck_id == deck.id)
        .order_by(RevisionCard.position, RevisionCard.id)
    ).all()
    if not cards:
        raise HTTPException(status_code=422, detail="This deck has no card yet.")
    payload = sheet_pdf(
        title=deck.title,
        cards=[
            {
                "front": card.front_md,
                "back": card.back_md,
                "image_path": (
                    str(settings.media_dir / card.image_path.rsplit("/", 1)[-1])
                    if card.image_path
                    else None
                ),
                "back_image_path": (
                    str(settings.media_dir / card.back_image_path.rsplit("/", 1)[-1])
                    if card.back_image_path
                    else None
                ),
            }
            for card in cards
        ],
        footer=f"OpenLearn — {len(cards)} cartes",
    )
    filename = f"cards-{deck.id}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
