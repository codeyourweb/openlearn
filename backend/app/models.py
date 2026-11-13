# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""ORM models for OpenLearn.

Design notes
------------
* A live game session keeps a *snapshot* of the quiz (questions, options,
  time limits, scoring policy, and the language chosen for that run). Editing a
  quiz therefore never corrupts a running or past session.
* Participant reconnect tokens are stored hashed; the plain token only ever
  lives in the participant's browser.
* Translations are stored as JSON maps ``{"fr": "...", "de": "..."}`` next to
  the canonical English text. A quiz is not required to be translated into
  every supported language: ``Quiz.languages`` lists what actually exists.
* Publication is a state machine (``draft -> private|pending -> public``)
  moderated by an administrator unless the author is trusted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Languages offered by the interface and by AI translation.
SUPPORTED_LANGUAGES = ("en", "fr", "it", "es", "de", "ru", "zh", "ja", "pt", "hi", "bn", "ar")

QUIZ_STATUSES = ("draft", "private", "pending", "public", "rejected")
QUIZ_MODES = ("qcm", "swipe", "adventure")


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # An administrator runs the instance, including its AI, mail and SSO
    # configuration.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # A moderator validates content like an administrator, but never reaches
    # the instance configuration.
    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False)
    # A trusted author publishes without prior moderation.
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password reset or account compromise: every session token
    # minted before the change stops validating.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # An address typed at sign-up is a claim until someone opens the link sent to
    # it. Accounts that existed before this column are trusted: the migration
    # backfills them as confirmed, so nobody is locked out by an upgrade.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quizzes: Mapped[list[Quiz]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Quiz.owner_id",
    )
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_staff(self) -> bool:
        """True for anyone who validates content: an administrator or a moderator."""
        return bool(self.is_admin or self.is_moderator)


class ApiKey(Base):
    """Long lived credential for third party API clients (``X-API-Key``)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys")


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # "zero" -> wrong answer scores 0, "penalty" -> wrong answer loses points
    wrong_answer_policy: Mapped[str] = mapped_column(String(10), default="zero")
    # "qcm" -> 2-8 answers, "swipe" -> yes/no cards, "poll" -> no right answer
    mode: Mapped[str] = mapped_column(String(10), default="qcm")
    # Who may read the tallies: "private" (author only), "respondents" (anyone
    # who took part) or "public" (anyone who can see the quiz).
    results_visibility: Mapped[str] = mapped_column(String(12), default="respondents")
    # Hash of the working copy the stored translations were produced from, so a
    # second translate on unchanged content costs nothing.
    translation_hash: Mapped[str] = mapped_column(String(64), default="")
    # Kept in sync with ``status == "public"`` for the existing queries.
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    moderation_note: Mapped[str] = mapped_column(String(300), default="")

    # Timing. "per_question" uses each question's own limit, "global" gives the
    # whole run one budget, "none" means no countdown at all.
    timer_mode: Mapped[str] = mapped_column(String(14), default="per_question")
    global_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Assessment. `max_attempts` is the number of runs one candidate may take
    # (0 = as many as they like); a grant row adds exactly one more. The share
    # token opens a private quiz to candidates who hold the link, without
    # putting it in the catalogue.
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)
    share_token: Mapped[str | None] = mapped_column(String(48), unique=True)

    # Internationalisation
    is_multilingual: Mapped[bool] = mapped_column(Boolean, default=False)
    default_language: Mapped[str] = mapped_column(String(5), default="en")
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    title_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    description_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)

    # Content provenance and review state
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    legal_status: Mapped[str] = mapped_column(String(12), default="")  # ""|approved|blocked
    legal_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hash: Mapped[str] = mapped_column(String(64), default="")
    answer_status: Mapped[str] = mapped_column(String(12), default="")  # ""|ok|corrected
    answer_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_hash: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # Branching ("adventure") mode: start node and story-level ending texts.
    adventure_start_key: Mapped[str] = mapped_column(String(60), default="")
    adventure_settings: Mapped[dict] = mapped_column(JSON, default=dict)

    # Versioning. The working copy above is always the *next* version being
    # edited; ``published_version_number`` is what the public catalogue serves.
    published_version_number: Mapped[int] = mapped_column(Integer, default=0)

    owner: Mapped[User] = relationship(back_populates="quizzes", foreign_keys=[owner_id])
    questions: Mapped[list[Question]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="Question.position"
    )
    reviews: Mapped[list[AiReview]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )
    adventure_attributes: Mapped[list[AdventureAttribute]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="AdventureAttribute.position"
    )
    adventure_nodes: Mapped[list[AdventureNode]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="AdventureNode.position"
    )
    versions: Mapped[list[QuizVersion]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="QuizVersion.number"
    )

    @property
    def multiple_answers_supported(self) -> bool:
        return self.mode == "qcm"


class QuizVersion(Base):
    """An immutable snapshot of a quiz, usable to publish or to roll back.

    ``payload`` holds the whole quiz in the shape accepted by ``QuizIn``:
    metadata, questions with their options, or the story graph for
    ``adventure`` quizzes. The working copy keeps living in the regular tables
    so the editor stays simple; a snapshot is only written when a version is
    saved for publication.
    """

    __tablename__ = "quiz_versions"
    __table_args__ = (UniqueConstraint("quiz_id", "number", name="uq_quiz_version_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    # draft (private checkpoint) | pending (awaiting moderation) | published |
    # superseded (was published, replaced) | rejected
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Set when the version was ever approved: a rollback may republish it as-is.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quiz: Mapped[Quiz] = relationship(back_populates="versions")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text_html: Mapped[str] = mapped_column(Text)
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    image_path: Mapped[str | None] = mapped_column(String(200))
    # {"x", "y", "zoom"} — how the author framed the picture; empty means the
    # whole image, letterboxed.
    image_framing: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=30)
    points: Mapped[int] = mapped_column(Integer, default=100)
    # Polls have no answer key to infer "several answers allowed" from, so the
    # author states it explicitly.
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    options: Mapped[list[Option]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="Option.position"
    )

    @property
    def multiple_answers(self) -> bool:
        """Several answers are allowed.

        A scored quiz infers it from its answer key (more than one correct
        option); a poll has no key at all, so the author's switch decides.
        """
        if self.allow_multiple:
            return True
        return sum(1 for option in self.options if option.is_correct) > 1


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(500))
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[Question] = relationship(back_populates="options")


class AiReview(Base):
    """One AI review pass over a quiz.

    ``content_hash`` pins the review to the exact version that was examined, so
    an unchanged quiz is never reviewed twice while any edit invalidates it.
    """

    __tablename__ = "ai_reviews"
    __table_args__ = (UniqueConstraint("quiz_id", "kind", "content_hash", name="uq_review_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # legal|answers|translate
    status: Mapped[str] = mapped_column(String(12))  # approved|blocked|ok|corrected|failed
    model: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list[dict]] = mapped_column(JSON, default=list)
    corrections: Mapped[list[dict]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    requested_by_id: Mapped[int | None] = mapped_column(Integer)
    requested_ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    quiz: Mapped[Quiz] = relationship(back_populates="reviews")


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    join_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    quiz_id: Mapped[int | None] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"))
    host_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    host_token_hash: Mapped[str] = mapped_column(String(64), default="")
    quiz_title: Mapped[str] = mapped_column(String(120))
    quiz_mode: Mapped[str] = mapped_column(String(10), default="qcm")
    language: Mapped[str] = mapped_column(String(5), default="en")
    wrong_answer_policy: Mapped[str] = mapped_column(String(10), default="zero")
    timer_mode: Mapped[str] = mapped_column(String(14), default="per_question")
    global_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="lobby")  # lobby|active|finished|cancelled
    is_solo: Mapped[bool] = mapped_column(Boolean, default=False)
    current_index: Mapped[int] = mapped_column(Integer, default=-1)
    phase: Mapped[str] = mapped_column(String(12), default="idle")  # idle|question|reveal|finished
    question_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "global" timer mode: one deadline for the whole run.
    run_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list[SessionQuestion]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="SessionQuestion.position"
    )
    participants: Mapped[list[Participant]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionQuestion(Base):
    __tablename__ = "session_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    source_question_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    text_html: Mapped[str] = mapped_column(Text)
    # The wording is frozen when the run starts, in every language the quiz
    # offered: a player who switches language mid-run reads the same question,
    # not a stale one.
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    image_path: Mapped[str | None] = mapped_column(String(200))
    # Frozen with the wording: a run keeps the framing it started with.
    image_framing: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer, default=100)
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[GameSession] = relationship(back_populates="questions")
    options: Mapped[list[SessionOption]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="SessionOption.position"
    )


class SessionOption(Base):
    __tablename__ = "session_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_question_id: Mapped[int] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), index=True
    )
    source_option_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(500))
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[SessionQuestion] = relationship(back_populates="options")


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("session_id", "nickname", name="uq_participant_nickname"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    nickname: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[GameSession] = relationship(back_populates="participants")
    answers: Mapped[list[Answer]] = relationship(back_populates="participant", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("participant_id", "session_question_id", name="uq_answer_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)
    session_question_id: Mapped[int] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), index=True
    )
    selected: Mapped[list[int]] = mapped_column(JSON, default=list)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    response_ms: Mapped[int] = mapped_column(Integer, default=0)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    participant: Mapped[Participant] = relationship(back_populates="answers")


class SecurityEvent(Base):
    """Minimal audit trail for authentication and game events (OWASP A09)."""

    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event: Mapped[str] = mapped_column(String(60), index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(String(300), default="")


class AdventureAttribute(Base):
    """One score track of a branching quiz (``vie``, ``mana``, ``agilité``...).

    ``death_at_or_below`` and ``victory_at_or_above`` are the author's optional
    early-end rules: a run stops as soon as one attribute crosses them.
    """

    __tablename__ = "adventure_attributes"
    __table_args__ = (UniqueConstraint("quiz_id", "key", name="uq_adventure_attribute_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    label_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    initial_value: Mapped[int] = mapped_column(Integer, default=0)
    min_value: Mapped[int | None] = mapped_column(Integer)
    max_value: Mapped[int | None] = mapped_column(Integer)
    death_at_or_below: Mapped[int | None] = mapped_column(Integer)
    victory_at_or_above: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped[Quiz] = relationship(back_populates="adventure_attributes")


class AdventureNode(Base):
    """A story step: either a question with choices, or an ending."""

    __tablename__ = "adventure_nodes"
    __table_args__ = (UniqueConstraint("quiz_id", "key", name="uq_adventure_node_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10), default="question")  # question|ending
    text_html: Mapped[str] = mapped_column(Text, default="")
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    image_path: Mapped[str | None] = mapped_column(String(200))
    image_framing: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    background_path: Mapped[str | None] = mapped_column(String(200))
    pos_x: Mapped[int] = mapped_column(Integer, default=0)
    pos_y: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped[Quiz] = relationship(back_populates="adventure_nodes")
    choices: Mapped[list[AdventureChoice]] = relationship(
        back_populates="node", cascade="all, delete-orphan", order_by="AdventureChoice.position"
    )
    outcomes: Mapped[list[AdventureOutcome]] = relationship(
        back_populates="node", cascade="all, delete-orphan", order_by="AdventureOutcome.priority"
    )


class AdventureChoice(Base):
    """An answer. ``target_key`` empty means the run ends here ("exit" branch)."""

    __tablename__ = "adventure_choices"
    __table_args__ = (UniqueConstraint("node_id", "key", name="uq_adventure_choice_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("adventure_nodes.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(String(500))
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    target_key: Mapped[str | None] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0)

    node: Mapped[AdventureNode] = relationship(back_populates="choices")
    effects: Mapped[list[AdventureEffect]] = relationship(
        back_populates="choice", cascade="all, delete-orphan"
    )


class AdventureEffect(Base):
    """Delta applied to one attribute when a choice is taken."""

    __tablename__ = "adventure_effects"

    id: Mapped[int] = mapped_column(primary_key=True)
    choice_id: Mapped[int] = mapped_column(ForeignKey("adventure_choices.id", ondelete="CASCADE"), index=True)
    attribute_key: Mapped[str] = mapped_column(String(40))
    delta: Mapped[int] = mapped_column(Integer, default=0)

    choice: Mapped[AdventureChoice] = relationship(back_populates="effects")


class AdventureOutcome(Base):
    """Text shown at an ending, selected from the visitor's final attributes.

    ``kind`` is ``highest`` (the attribute is the highest one), ``lowest``, or
    ``range`` (the attribute value falls inside ``range_min``..``range_max``).
    """

    __tablename__ = "adventure_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("adventure_nodes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10), default="highest")
    attribute_key: Mapped[str | None] = mapped_column(String(40))
    range_min: Mapped[int | None] = mapped_column(Integer)
    range_max: Mapped[int | None] = mapped_column(Integer)
    text_html: Mapped[str] = mapped_column(Text, default="")
    text_translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    node: Mapped[AdventureNode] = relationship(back_populates="outcomes")


class AdventureRun(Base):
    """One solo play-through of a branching quiz.

    The validated graph is snapshotted at start time, exactly like live
    sessions do, so editing the quiz cannot corrupt a run in progress.
    """

    __tablename__ = "adventure_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    current_key: Mapped[str] = mapped_column(String(60), default="")
    path: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|finished
    # Story timer: the moment the current scene must be answered by.
    node_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ending_key: Mapped[str | None] = mapped_column(String(60))
    ending_kind: Mapped[str | None] = mapped_column(String(12))
    outcome_text_html: Mapped[str] = mapped_column(Text, default="")
    background_path: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Wiki
# ---------------------------------------------------------------------------
WIKI_STATUSES = ("draft", "private", "pending", "public", "rejected")
# owner: everything, including publication requests. maintainer: writes pages
# directly. contributor: reads and submits proposals that an owner or a
# maintainer has to accept.
WIKI_ROLES = ("maintainer", "contributor")


class Wiki(Base):
    """A collection of markdown pages, published as a whole.

    Pages are the unit of editing; the wiki is the unit of sharing, of
    moderation and of the search and chat scope. A public wiki is readable by
    anyone, including anonymous visitors.
    """

    __tablename__ = "wikis"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    cover_image: Mapped[str | None] = mapped_column(String(200))
    moderation_note: Mapped[str] = mapped_column(String(300), default="")
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Obsidian-style canvas: nodes and edges as JSON, one per wiki.
    canvas: Mapped[dict] = mapped_column(JSON, default=dict)
    default_language: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list[WikiPage]] = relationship(
        back_populates="wiki", cascade="all, delete-orphan", order_by="WikiPage.position"
    )
    members: Mapped[list[WikiMember]] = relationship(
        back_populates="wiki", cascade="all, delete-orphan"
    )


class WikiPage(Base):
    """One markdown document. ``content_md`` is the current working copy."""

    __tablename__ = "wiki_pages"
    __table_args__ = (UniqueConstraint("wiki_id", "slug", name="uq_wiki_page_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    wiki_id: Mapped[int] = mapped_column(ForeignKey("wikis.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(180), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content_md: Mapped[str] = mapped_column(Text, default="")
    # Free-form tags, shown as chips in the page header.
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Menu tree: a page may hang under another one, any depth (bounded on write).
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="SET NULL"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    current_version_number: Mapped[int] = mapped_column(Integer, default=0)
    # Hash of ``content_md`` when the last AI review ran, so re-running an
    # unchanged page costs nothing.
    review_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    wiki: Mapped[Wiki] = relationship(back_populates="pages")


class WikiPageVersion(Base):
    """Immutable snapshot, written on every accepted save."""

    __tablename__ = "wiki_page_versions"
    __table_args__ = (UniqueConstraint("page_id", "number", name="uq_wiki_page_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content_md: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WikiPageDraft(Base):
    """Text typed in the editor that nobody has saved as a version yet.

    One row per page: co-editors share the working copy. The published page is
    never touched by it, so a reader keeps seeing the last saved version and an
    autosave can no longer rewrite a page behind its author's back.
    """

    __tablename__ = "wiki_page_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="CASCADE"), unique=True, index=True
    )
    content_md: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WikiProposal(Base):
    """A suggested rewrite from somebody who may not write the page directly."""

    __tablename__ = "wiki_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    base_number: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    content_md: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WikiReference(Base):
    """A citation attached to a page: an outside source or a sibling page.

    External references are what a bibliography is made of; internal ones name a
    page explicitly, without forcing the author to write a ``[[wikilink]]`` in
    the prose. Links detected in the text are computed on the fly and never
    stored here.
    """

    __tablename__ = "wiki_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10), default="external")
    url: Mapped[str] = mapped_column(String(800), default="")
    target_slug: Mapped[str] = mapped_column(String(180), default="")
    label: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WikiTemplate(Base):
    """Reusable markdown skeleton, owned by one wiki and shared with its writers.

    A template is authored like a page (markdown, previewed the same way) and
    applied when a new page is created, so a wiki keeps its own house style
    instead of every author inventing a structure.
    """

    __tablename__ = "wiki_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    wiki_id: Mapped[int] = mapped_column(ForeignKey("wikis.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300), default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WikiMember(Base):
    """Extra rights on somebody else's wiki."""

    __tablename__ = "wiki_members"
    __table_args__ = (UniqueConstraint("wiki_id", "user_id", name="uq_wiki_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    wiki_id: Mapped[int] = mapped_column(ForeignKey("wikis.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12), default="contributor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    wiki: Mapped[Wiki] = relationship(back_populates="members")


class QuizAttemptGrant(Base):
    """One extra run allowed to one candidate, decided by the author.

    Attempts are counted from the sessions themselves, so history is never
    rewritten; a grant simply raises the ceiling by one.
    """

    __tablename__ = "quiz_attempt_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WikiQuizLink(Base):
    """A questionnaire that belongs to a wiki's subject.

    The relation is many-to-many and carries no order: a wiki may gather several
    questionnaires (one per chapter, one per audience), and the same
    questionnaire may illustrate two wikis.
    """

    __tablename__ = "wiki_quizzes"
    __table_args__ = (UniqueConstraint("wiki_id", "quiz_id", name="uq_wiki_quiz"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    wiki_id: Mapped[int] = mapped_column(ForeignKey("wikis.id", ondelete="CASCADE"), index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WikiLink(Base):
    """Resolved ``[[wikilink]]`` edge, rebuilt whenever a page is saved."""

    __tablename__ = "wiki_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    wiki_id: Mapped[int] = mapped_column(ForeignKey("wikis.id", ondelete="CASCADE"), index=True)
    from_page_id: Mapped[int] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    target_slug: Mapped[str] = mapped_column(String(180), index=True)
    to_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("wiki_pages.id", ondelete="SET NULL")
    )


class AiJob(Base):
    """One long running model task, polled by the page that started it.

    ``key`` makes a job unique while it is queued or running: the router
    refuses a second ``wiki.generate`` for the same target instead of paying
    twice for the same work.
    """

    __tablename__ = "ai_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    target_type: Mapped[str] = mapped_column(String(12), default="wiki")  # wiki|page|quiz
    target_id: Mapped[int | None] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WikiChat(Base):
    """A RAG conversation grounded strictly in the wikis the reader may see."""

    __tablename__ = "wiki_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WikiChatMessage(Base):
    __tablename__ = "wiki_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("wiki_chats.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10), default="user")  # user|assistant
    content: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevisionDeck(Base):
    """A deck of revision cards, optionally born from a wiki page or a quiz.

    The deck is the unit of sharing: it can stay private, be published in the
    catalogue, or simply hang off the wiki/quiz it was made from. Cards are
    deliberately plain (a front, a back, an optional image) so that the same
    object serves a language course, a technical curriculum or a horse-riding
    lesson without any per-domain code.
    """

    __tablename__ = "revision_decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Where the cards came from, when they were not typed by hand. Both are
    # optional and survive a deletion of the source (SET NULL).
    wiki_id: Mapped[int | None] = mapped_column(
        ForeignKey("wikis.id", ondelete="SET NULL"), index=True
    )
    quiz_id: Mapped[int | None] = mapped_column(
        ForeignKey("quizzes.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Shape of every card in the deck, as "width:height". 2:3 is the portrait
    # of a printed character card; a picture card is useless in a square.
    aspect: Mapped[str] = mapped_column(String(5), default="2:3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    cards: Mapped[list[RevisionCard]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", order_by="RevisionCard.position"
    )


class RevisionCard(Base):
    """One card: markdown on the front, markdown on the back, an optional image."""

    __tablename__ = "revision_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(
        ForeignKey("revision_decks.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    front_md: Mapped[str] = mapped_column(Text, default="")
    back_md: Mapped[str] = mapped_column(Text, default="")
    # Same media pipeline as the wiki and the quizzes: re-encoded, allowlisted.
    # Both faces can carry one: a card may be a picture on each side.
    image_path: Mapped[str | None] = mapped_column(String(200))
    back_image_path: Mapped[str | None] = mapped_column(String(200))
    # How each face frames its picture: a card is 2:3, a photo rarely is.
    image_framing: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    back_image_framing: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    # "manual" | "wiki" | "quiz" — kept for the author's sake, not for logic.
    source: Mapped[str] = mapped_column(String(10), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deck: Mapped[RevisionDeck] = relationship(back_populates="cards")


class RevisionReview(Base):
    """How one learner stands on one card: three boxes, no spaced-repetition maths.

    ``box`` 0 = to review, 1 = getting there, 2 = known. A "known" answer moves
    the card one box up, "again" sends it straight back to 0: that is the whole
    algorithm, and it is honest about being one.
    """

    __tablename__ = "revision_reviews"
    __table_args__ = (UniqueConstraint("card_id", "user_id", name="uq_revision_card_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("revision_cards.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    box: Mapped[int] = mapped_column(Integer, default=0)
    seen: Mapped[int] = mapped_column(Integer, default=0)
    known: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AppSetting(Base):
    """Administrator-editable setting, overriding the OL_* environment value.

    Values are stored as JSON so a section can hold booleans, numbers or lists
    without a column per option. Secrets are stored as-is but never returned by
    the API: the admin UI only learns whether a value is set.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AiErrorLog(Base):
    """One failed call to the model provider, readable by administrators.

    The provider message is truncated and never contains our API key, but it
    can quote user content: this table is admin-only and pruned with the rest
    of the audit trail.
    """

    __tablename__ = "ai_error_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    operation: Mapped[str] = mapped_column(String(40), default="chat")
    model: Mapped[str] = mapped_column(String(120), default="")
    base_url: Mapped[str] = mapped_column(String(200), default="")
    status_code: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(Text, default="")


class EmailVerificationToken(Base):
    """Single-use link that proves the visitor owns the address they typed."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str] = mapped_column(String(64), default="")


class PasswordResetToken(Base):
    """Single-use, short-lived password reset token (stored hashed)."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str] = mapped_column(String(64), default="")


class SsoProvider(Base):
    """An OpenID Connect (or SAML 2.0) identity provider added by an admin."""

    __tablename__ = "sso_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8), default="oidc")  # oidc | saml
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # OIDC
    issuer: Mapped[str] = mapped_column(String(300), default="")
    client_id: Mapped[str] = mapped_column(String(200), default="")
    client_secret: Mapped[str] = mapped_column(String(400), default="")
    scopes: Mapped[str] = mapped_column(String(200), default="openid email profile")

    # SAML 2.0
    metadata_url: Mapped[str] = mapped_column(String(400), default="")
    entity_id: Mapped[str] = mapped_column(String(300), default="")
    sso_url: Mapped[str] = mapped_column(String(400), default="")
    x509_cert: Mapped[str] = mapped_column(Text, default="")

    # Account mapping
    auto_create_users: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_domains: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalIdentity(Base):
    """Link between a local account and a subject at an identity provider."""

    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject", name="uq_identity_provider_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("sso_providers.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AudioSegment(Base):
    """One synthesised piece of text, shared by every document that contains it.

    The cache is the point: re-editing a paragraph re-synthesises that paragraph
    and nothing else. The key covers everything the audio depends on, so a voice
    or language change cannot return the wrong file.
    """

    __tablename__ = "audio_segments"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_audio_segment_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    voice: Mapped[str] = mapped_column(String(10), default="female")
    # The intonation is part of the identity of the file: the same paragraph read
    # formally and warmly are two recordings, not one.
    tone: Mapped[str] = mapped_column(String(16), default="neutral")
    model: Mapped[str] = mapped_column(String(60), default="")
    path: Mapped[str] = mapped_column(String(200))
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AudioRendition(Base):
    """A playable transcript of one document, in one voice.

    Segments are stored in order rather than concatenated: the reader advances
    through them, which is what makes resuming and section skipping possible
    without an audio editor on the server.
    """

    __tablename__ = "audio_renditions"
    __table_args__ = (
        Index("ix_audio_rendition_target", "owner_type", "owner_id", "language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # page | quiz | node
    owner_type: Mapped[str] = mapped_column(String(8))
    owner_id: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(5), default="en")
    voice: Mapped[str] = mapped_column(String(10), default="female")
    # How the narrator carries the text (neutral, formal, warm, lively). Stored so
    # a rendition says what it is, and so two readings of one page can coexist.
    tone: Mapped[str] = mapped_column(String(16), default="neutral")
    model: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    # Hash of the script the audio was made from: an edited document shows no
    # player until it is regenerated, instead of playing yesterday's text.
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    total_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    segments: Mapped[list] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LogTarget(Base):
    """One place the audit trail is shipped to: a syslog collector or a webhook.

    A target is a row rather than a pair of settings keys so an instance can feed
    several XDR/SIEM at once — a Splunk over HTTP, a Sekoia with its own
    ``intake-key`` header, and a local rsyslog — and each one fails on its own.
    The legacy ``log.syslog_*`` / ``log.http_*`` settings stay as the bootstrap:
    they are turned into targets when this table is empty, so an existing
    installation keeps forwarding without touching anything.
    """

    __tablename__ = "log_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(8), default="http")  # syslog | http
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # syslog
    host: Mapped[str] = mapped_column(String(200), default="")
    port: Mapped[int] = mapped_column(Integer, default=514)
    protocol: Mapped[str] = mapped_column(String(4), default="udp")  # udp | tcp | tls
    facility: Mapped[int] = mapped_column(Integer, default=13)
    hostname: Mapped[str] = mapped_column(String(80), default="")
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)

    # http(s) post
    url: Mapped[str] = mapped_column(String(500), default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    # Extra request headers as a JSON object: Sekoia wants ``intake-key``,
    # Splunk HEC wants ``Authorization: Splunk <token>``, others want nothing.
    # A value whose name looks like a credential is never returned by the API.
    headers: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
