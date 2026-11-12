# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Pydantic request/response schemas and serialisers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .adventure import slug_key as _slug_key
from .models import SUPPORTED_LANGUAGES
from .sanitize import html_to_text, sanitize_html, sanitize_plain

LanguageCode = Literal["en", "fr", "it", "es", "de", "ru", "zh", "ja", "pt", "hi", "bn", "ar"]


def _clean_translation_map(value: dict | None, *, html: bool, max_length: int) -> dict[str, str]:
    """Validate a ``{language: text}`` map coming from the editor."""
    if not value:
        return {}
    cleaned: dict[str, str] = {}
    for language, text in value.items():
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}.")
        if not isinstance(text, str) or not text.strip():
            continue
        if html:
            candidate = sanitize_html(text)
            if not html_to_text(candidate):
                continue
            cleaned[language] = candidate[:20_000]
        else:
            candidate = sanitize_plain(text, max_length=max_length)
            if candidate:
                cleaned[language] = candidate
    return cleaned


# ---------------------------------------------------------------------------
# Auth / account
# ---------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=2, max_length=60)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=60)
        if len(cleaned) < 2:
            raise ValueError("Display name is too short.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_admin: bool = False
    is_moderator: bool = False
    is_staff: bool = False
    is_trusted: bool = False
    # False until the visitor opened the link mailed at sign-up; accounts that
    # predate the feature are confirmed by the migration.
    email_verified: bool = True
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return sanitize_plain(value, max_length=60)


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # only returned once, at creation time


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------
class OptionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False
    translations: dict[str, str] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=500)
        if not cleaned:
            raise ValueError("Option text cannot be empty.")
        return cleaned

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=500)


class FramingIn(BaseModel):
    """How the author framed a picture inside its frame (percent + zoom)."""

    x: float = Field(default=50, ge=0, le=100)
    y: float = Field(default=50, ge=0, le=100)
    zoom: float = Field(default=1, ge=1, le=3)


class QuestionIn(BaseModel):
    text_html: str = Field(min_length=1, max_length=20_000)
    translations: dict[str, str] = Field(default_factory=dict)
    image_path: str | None = Field(default=None, max_length=200)
    image_framing: FramingIn | None = None
    time_limit_seconds: int = Field(default=30, ge=5, le=300)
    points: int = Field(default=100, ge=0, le=1000)
    # Only meaningful for polls; elsewhere several correct answers say it.
    allow_multiple: bool = False
    options: list[OptionIn] = Field(min_length=2, max_length=8)

    @field_validator("text_html")
    @classmethod
    def _clean_html(cls, value: str) -> str:
        cleaned = sanitize_html(value)
        if not html_to_text(cleaned):
            raise ValueError("Question text cannot be empty.")
        return cleaned

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=True, max_length=20_000)

    @field_validator("image_path")
    @classmethod
    def _clean_image(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        # Only paths produced by our own upload endpoint are accepted.
        if not value.startswith("/media/") or ".." in value:
            raise ValueError("Invalid image reference.")
        return value

    @model_validator(mode="after")
    def _validate_options(self) -> QuestionIn:
        # Whether an answer key is required depends on the quiz mode (a poll
        # has none), so that check lives in QuizIn.
        texts = [option.text.casefold() for option in self.options]
        if len(set(texts)) != len(texts):
            raise ValueError("Answer texts must be unique within a question.")
        return self



# ---------------------------------------------------------------------------
# Branching ("adventure") mode
# ---------------------------------------------------------------------------

class AdventureAttributeIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    translations: dict[str, str] = Field(default_factory=dict)
    initial_value: int = Field(default=0, ge=-1_000, le=1_000)
    min_value: int | None = Field(default=None, ge=-1_000, le=1_000)
    max_value: int | None = Field(default=None, ge=-1_000, le=1_000)
    death_at_or_below: int | None = Field(default=None, ge=-1_000, le=1_000)
    victory_at_or_above: int | None = Field(default=None, ge=-1_000, le=1_000)

    @field_validator("key")
    @classmethod
    def _clean_key(cls, value: str) -> str:
        return _slug_key(value, limit=40)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=80)
        if not cleaned:
            raise ValueError("Attribute label cannot be empty.")
        return cleaned

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=80)


class AdventureEffectIn(BaseModel):
    attribute: str = Field(min_length=1, max_length=40)
    delta: int = Field(ge=-1_000, le=1_000)

    @field_validator("attribute")
    @classmethod
    def _clean_attribute(cls, value: str) -> str:
        # Same rule as `AdventureAttributeIn.key`: a reference written with
        # accents or spaces has to point at the attribute it names.
        return _slug_key(value, limit=40)


class AdventureChoiceIn(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=500)
    translations: dict[str, str] = Field(default_factory=dict)
    target: str | None = Field(default=None, max_length=60)
    effects: list[AdventureEffectIn] = Field(default_factory=list, max_length=12)

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=500)
        if not cleaned:
            raise ValueError("Choice text cannot be empty.")
        return cleaned

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=500)


class AdventureOutcomeIn(BaseModel):
    kind: Literal["highest", "lowest", "range", "default"] = "highest"
    attribute: str | None = Field(default=None, max_length=40)
    range_min: int | None = Field(default=None, ge=-1_000, le=1_000)
    range_max: int | None = Field(default=None, ge=-1_000, le=1_000)
    text_html: str = Field(default="", max_length=20_000)
    translations: dict[str, str] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, le=999)

    @field_validator("attribute")
    @classmethod
    def _clean_attribute(cls, value: str | None) -> str | None:
        return _slug_key(value, limit=40) if value else value

    @field_validator("text_html")
    @classmethod
    def _clean_html(cls, value: str) -> str:
        return sanitize_html(value) if value else ""

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=True, max_length=20_000)


class AdventureNodeIn(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    kind: Literal["question", "ending"] = "question"
    text_html: str = Field(min_length=1, max_length=20_000)
    translations: dict[str, str] = Field(default_factory=dict)
    image_path: str | None = Field(default=None, max_length=200)
    image_framing: FramingIn | None = None
    background_path: str | None = Field(default=None, max_length=200)
    pos_x: int = Field(default=0, ge=-10_000, le=10_000)
    pos_y: int = Field(default=0, ge=-10_000, le=10_000)
    choices: list[AdventureChoiceIn] = Field(default_factory=list, max_length=8)
    outcomes: list[AdventureOutcomeIn] = Field(default_factory=list, max_length=40)

    @field_validator("key")
    @classmethod
    def _clean_key(cls, value: str) -> str:
        return _slug_key(value)

    @field_validator("text_html")
    @classmethod
    def _clean_html(cls, value: str) -> str:
        cleaned = sanitize_html(value)
        if not html_to_text(cleaned):
            raise ValueError("Node text cannot be empty.")
        return cleaned

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=True, max_length=20_000)


from .adventure import validate_adventure_graph  # noqa: E402  (no cycle: pure module)


class AdventureIn(BaseModel):
    """The whole branching graph, saved as one document by the editor."""

    start: str = Field(min_length=1, max_length=60)
    attributes: list[AdventureAttributeIn] = Field(min_length=1, max_length=12)
    nodes: list[AdventureNodeIn] = Field(min_length=1, max_length=200)
    death_text_html: str = Field(default="", max_length=20_000)
    death_translations: dict[str, str] = Field(default_factory=dict)
    death_background_path: str | None = Field(default=None, max_length=200)
    victory_text_html: str = Field(default="", max_length=20_000)
    victory_translations: dict[str, str] = Field(default_factory=dict)
    victory_background_path: str | None = Field(default=None, max_length=200)
    # Optional clock on a story: "none" | "global" | "per_node". Running out is
    # either a penalty on the attributes or an early death, as the author chose.
    timer_mode: Literal["none", "global", "per_node"] = "none"
    time_limit_seconds: int = Field(default=0, ge=0, le=7200)
    timeout_effect: Literal["penalty", "death"] = "penalty"
    timeout_penalty: int = Field(default=1, ge=0, le=10)
    timeout_penalty_attribute: str = Field(default="", max_length=60)

    @model_validator(mode="after")
    def _validate_timer(self) -> AdventureIn:
        if self.timer_mode != "none" and self.time_limit_seconds < 10:
            raise ValueError("A timed story needs at least 10 seconds.")
        if self.timer_mode == "none":
            self.time_limit_seconds = 0
        return self

    @field_validator("death_text_html", "victory_text_html")
    @classmethod
    def _clean_story_html(cls, value: str) -> str:
        return sanitize_html(value) if value else ""

    @field_validator("death_translations", "victory_translations")
    @classmethod
    def _clean_story_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=True, max_length=20_000)

    @model_validator(mode="after")
    def _validate_graph(self) -> AdventureIn:
        # Saving is tolerant: a half-drawn story stays a draft. Publishing runs
        # the strict pass (see the visibility endpoint).
        validate_adventure_graph(self, strict=False)
        return self


class QuizIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    wrong_answer_policy: Literal["zero", "penalty"] = "zero"
    mode: Literal["qcm", "swipe", "adventure", "poll"] = "qcm"
    # "per_question" -> each question carries its own countdown, "global" -> one
    # budget for the whole run, "none" -> no countdown at all.
    timer_mode: Literal["per_question", "global", "none"] = "per_question"
    global_time_limit_seconds: int = Field(default=0, ge=0, le=7200)
    is_public: bool = False
    # Who may read the tallies: the author only, the people who answered, or
    # everyone who can see the quiz.
    results_visibility: Literal["private", "respondents", "public"] = "respondents"
    # 0 = no ceiling; N = each signed-in candidate may take the questionnaire N
    # times, plus one more per explicit grant from the author.
    max_attempts: int = Field(default=0, ge=0, le=10)
    default_language: LanguageCode = "en"
    title_translations: dict[str, str] = Field(default_factory=dict)
    description_translations: dict[str, str] = Field(default_factory=dict)
    questions: list[QuestionIn] = Field(default_factory=list, max_length=200)
    adventure: AdventureIn | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=120)
        if len(cleaned) < 3:
            raise ValueError("Title is too short.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return sanitize_plain(value, max_length=2000)

    @field_validator("title_translations")
    @classmethod
    def _clean_title_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=120)

    @field_validator("description_translations")
    @classmethod
    def _clean_description_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=2000)

    @model_validator(mode="after")
    def _validate_timer(self) -> QuizIn:
        if self.timer_mode == "global":
            if self.global_time_limit_seconds < 30:
                raise ValueError("A global timer needs at least 30 seconds.")
        else:
            self.global_time_limit_seconds = 0
        return self

    @model_validator(mode="after")
    def _validate_mode(self) -> QuizIn:
        if self.mode == "adventure":
            if self.adventure is None:
                raise ValueError("Adventure quizzes need a story graph.")
            if self.questions:
                raise ValueError("Adventure quizzes cannot contain linear questions.")
            return self
        if self.adventure is not None:
            raise ValueError("Only adventure quizzes can carry a story graph.")
        if not self.questions:
            raise ValueError("A quiz needs at least one question.")
        if self.mode == "swipe":
            for question in self.questions:
                if len(question.options) != 2:
                    raise ValueError("Swipe questions need exactly two answers (Yes/No).")
                if sum(1 for option in question.options if option.is_correct) != 1:
                    raise ValueError("A swipe question needs exactly one correct answer.")
        elif self.mode == "poll":
            # A poll carries no answer key: any leftover flag would later be
            # read as "this respondent was right", so it is dropped here.
            for question in self.questions:
                for option in question.options:
                    option.is_correct = False
                question.points = 0
        else:
            for question in self.questions:
                if not any(option.is_correct for option in question.options):
                    raise ValueError("Each question needs at least one correct answer.")
                if all(option.is_correct for option in question.options):
                    raise ValueError("At least one answer must be wrong.")
        return self


class AdventureRunIn(BaseModel):
    language: str | None = Field(default=None, max_length=5)


class AdventureChooseIn(BaseModel):
    choice: str = Field(min_length=1, max_length=60)


class QuizVersionOut(BaseModel):
    number: int
    status: str
    created_at: datetime
    published_at: datetime | None = None
    approved_at: datetime | None = None
    note: str = ""
    content_hash: str = ""
    question_count: int = 0
    node_count: int = 0
    title: str = ""


class QuizSummaryOut(BaseModel):
    id: int
    title: str
    description: str
    question_count: int
    wrong_answer_policy: str
    mode: str = "qcm"
    status: str = "public"
    is_public: bool
    languages: list[str] = Field(default_factory=list)
    default_language: str = "en"
    owner_id: int
    owner_name: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Draft (autosave) payloads
# ---------------------------------------------------------------------------
class OptionDraftIn(BaseModel):
    """An option as it may look mid-edit: text can still be empty."""

    text: str = Field(default="", max_length=500)
    is_correct: bool = False
    translations: dict[str, str] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        return sanitize_plain(value, max_length=500)

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=500)


class QuestionDraftIn(BaseModel):
    """A question as it may look mid-edit: no answer key required yet."""

    text_html: str = Field(default="", max_length=20_000)
    translations: dict[str, str] = Field(default_factory=dict)
    image_path: str | None = Field(default=None, max_length=200)
    time_limit_seconds: int = Field(default=30, ge=5, le=300)
    points: int = Field(default=0, ge=0, le=1000)
    allow_multiple: bool = False
    options: list[OptionDraftIn] = Field(default_factory=list, max_length=8)

    @field_validator("text_html")
    @classmethod
    def _clean_html(cls, value: str) -> str:
        return sanitize_html(value)

    @field_validator("translations")
    @classmethod
    def _clean_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=True, max_length=20_000)

    @field_validator("image_path")
    @classmethod
    def _clean_image(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not value.startswith("/media/") or ".." in value:
            raise ValueError("Invalid image reference.")
        return value


class QuizDraftIn(BaseModel):
    """Autosaved working copy: structurally valid, editorially unfinished.

    Publication still goes through ``QuizIn``, which enforces the answer key,
    the option count and a complete story graph.
    """

    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    wrong_answer_policy: Literal["zero", "penalty"] = "zero"
    mode: Literal["qcm", "swipe", "adventure", "poll"] = "qcm"
    timer_mode: Literal["per_question", "global", "none"] = "per_question"
    global_time_limit_seconds: int = Field(default=0, ge=0, le=7200)
    results_visibility: Literal["private", "respondents", "public"] = "respondents"
    # 0 = no ceiling; N = each signed-in candidate may take the questionnaire N
    # times, plus one more per explicit grant from the author.
    max_attempts: int = Field(default=0, ge=0, le=10)
    default_language: LanguageCode = "en"
    title_translations: dict[str, str] = Field(default_factory=dict)
    description_translations: dict[str, str] = Field(default_factory=dict)
    questions: list[QuestionDraftIn] = Field(default_factory=list, max_length=200)
    adventure: AdventureIn | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        return sanitize_plain(value, max_length=120)

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return sanitize_plain(value, max_length=2000)

    @field_validator("title_translations")
    @classmethod
    def _clean_title_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=120)

    @field_validator("description_translations")
    @classmethod
    def _clean_description_translations(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_translation_map(value, html=False, max_length=2000)


class QuizVisibilityIn(BaseModel):
    visibility: Literal["draft", "private", "public"]


class QuizPublishIn(BaseModel):
    """Publication request: the author states whether the quiz goes public."""

    visibility: Literal["private", "public"] = "public"
    note: str = Field(default="", max_length=300)


class ReviewOut(BaseModel):
    id: int
    kind: str
    status: str
    summary: str
    findings: list[dict] = Field(default_factory=list)
    corrections: list[dict] = Field(default_factory=list)
    model: str = ""
    created_at: datetime
    stale: bool = False


class QuizReviewStateOut(BaseModel):
    legal_status: str = ""
    legal_checked_at: datetime | None = None
    answer_status: str = ""
    answer_checked_at: datetime | None = None
    reviews: list[ReviewOut] = Field(default_factory=list)
    ai_available: bool = False


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
class AiGenerateIn(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    question_count: int = Field(default=10, ge=1, le=50)
    mode: Literal["qcm", "swipe"] = "qcm"
    language: LanguageCode = "en"
    level: str = Field(default="", max_length=60)
    save: bool = False

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=300)
        if len(cleaned) < 3:
            raise ValueError("Topic is too short.")
        return cleaned


class AiAdventureIn(BaseModel):
    """What an author writes before the model drafts a whole story."""

    topic: str = Field(min_length=3, max_length=300)
    brief: str = Field(default="", max_length=1000)
    scene_count: int = Field(default=6, ge=3, le=12)
    language: LanguageCode = "en"
    level: str = Field(default="", max_length=60)
    # A generated story is saved as a draft the author can play and edit; keeping
    # it in memory only is useful for a preview, not for the normal flow.
    save: bool = True

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=300)
        if len(cleaned) < 3:
            raise ValueError("Topic is too short.")
        return cleaned

    @field_validator("brief")
    @classmethod
    def _clean_brief(cls, value: str) -> str:
        return sanitize_plain(value, max_length=1000)

    @field_validator("level")
    @classmethod
    def _clean_level(cls, value: str) -> str:
        return sanitize_plain(value, max_length=60)


class AiAdventureReviseIn(BaseModel):
    """An instruction about an existing story: the model rewrites it whole."""

    instruction: str = Field(min_length=3, max_length=1000)
    language: LanguageCode | None = None
    save: bool = False

    @field_validator("instruction")
    @classmethod
    def _clean_instruction(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=1000)
        if len(cleaned) < 3:
            raise ValueError("Instruction is too short.")
        return cleaned


class AiTranslateIn(BaseModel):
    languages: list[LanguageCode] = Field(min_length=1, max_length=7)
    overwrite: bool = False
    # Translate a single question (and its answers) from the question form, or
    # the whole quiz when omitted.
    question_index: int | None = Field(default=None, ge=0, le=199)

    @field_validator("languages")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AiReviewIn(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class AdminUserOut(UserOut):
    is_active: bool = True
    quiz_count: int = 0
    last_login_at: datetime | None = None


class AdminUserPatch(BaseModel):
    is_admin: bool | None = None
    is_moderator: bool | None = None
    is_trusted: bool | None = None
    is_active: bool | None = None


class ModerationIn(BaseModel):
    note: str = Field(default="", max_length=300)

    @field_validator("note")
    @classmethod
    def _clean(cls, value: str) -> str:
        return sanitize_plain(value, max_length=300)


# ---------------------------------------------------------------------------
# Game sessions
# ---------------------------------------------------------------------------
class SessionSummaryOut(BaseModel):
    id: int
    code: str
    status: str
    is_solo: bool
    quiz_title: str
    quiz_id: int | None = None
    quiz_mode: str | None = None
    question_count: int = 0
    participant_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    best_score: int | None = None
    rank: int | None = None


class AttemptPolicyIn(BaseModel):
    """0 = unlimited; N = N runs per signed-in candidate."""

    max_attempts: int = Field(default=0, ge=0, le=10)


class SessionCreateIn(BaseModel):
    mode: Literal["live", "solo"] = "live"
    nickname: str | None = Field(default=None, max_length=30)
    language: LanguageCode | None = None
    # A host may take part in their own live session; the participant row is
    # created up front so the lobby already shows them.
    play_as_host: bool = False

    @field_validator("nickname")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = sanitize_plain(value, max_length=30)
        return cleaned or None


class JoinIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)

    @field_validator("nickname")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=30)
        if not cleaned:
            raise ValueError("Nickname cannot be empty.")
        return cleaned


class AnswerIn(BaseModel):
    question_id: int
    option_ids: Annotated[list[int], Field(default_factory=list, max_length=8)]

    @field_validator("option_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


# ---------------------------------------------------------------------------
# Wiki
# ---------------------------------------------------------------------------
class WikiIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=2000)
    default_language: LanguageCode = "en"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=160)
        if len(cleaned) < 3:
            raise ValueError("Title is too short.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return sanitize_plain(value, max_length=2000)


class WikiTreePageIn(BaseModel):
    id: int = Field(ge=1)
    parent_id: int | None = Field(default=None, ge=1)
    position: int = Field(default=0, ge=0, le=100_000)


class WikiTreeIn(BaseModel):
    """The whole menu in one call: order and parent of every page."""

    # No trailing "= []": the factory already lives in the annotation, and a
    # second default makes newer pydantic refuse to build the model.
    pages: Annotated[list[WikiTreePageIn], Field(default_factory=list, max_length=500)]


class WikiReferenceIn(BaseModel):
    """A citation: an outside source, or a sibling page named explicitly."""

    kind: str = "external"
    url: str = Field(default="", max_length=800)
    target_slug: str = Field(default="", max_length=180)
    label: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=300)

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        cleaned = (value or "external").strip().lower()
        if cleaned not in {"external", "internal"}:
            raise ValueError("A reference is either external or internal.")
        return cleaned

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        if not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("An external reference must be an http(s) URL.")
        return cleaned

    @field_validator("label", "note", "target_slug")
    @classmethod
    def _plain(cls, value: str) -> str:
        return sanitize_plain(value or "", max_length=800)


class WikiPageIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=400_000)
    tags: Annotated[list[str], Field(default_factory=list, max_length=12)]
    note: str = Field(default="", max_length=300)
    # WYSIWYG saves may send HTML; the editor converts, this is a safety net.
    content_html: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=200)
        if not cleaned:
            raise ValueError("Title cannot be empty.")
        return cleaned

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in value or []:
            text = sanitize_plain(tag, max_length=40).lower()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned[:12]


class WikiProposalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=400_000)
    note: str = Field(default="", max_length=500)
    base_number: int = 0


class WikiMemberIn(BaseModel):
    email: EmailStr
    role: Literal["maintainer", "contributor"] = "contributor"


class WikiPublishIn(BaseModel):
    visibility: Literal["private", "public"] = "public"


class WikiReviewIn(BaseModel):
    note: str = Field(default="", max_length=500)


class WikiCanvasIn(BaseModel):
    canvas: dict = Field(default_factory=dict)


class WikiQuizLinkIn(BaseModel):
    quiz_id: int


class WikiQuizGenerateIn(BaseModel):
    """What to build from the wiki: a scored QCM or a swipe deck."""

    mode: Literal["qcm", "swipe"] = "qcm"
    count: int = Field(default=8, ge=3, le=20)
    language: LanguageCode = "en"
    brief: str = Field(default="", max_length=2000)
    page_ids: Annotated[list[int], Field(default_factory=list, max_length=60)]


class WikiAiJobIn(BaseModel):
    kind: Literal["generate", "review", "grammar", "compliance", "expand", "fill"] = "generate"
    wiki_id: int | None = None
    page_id: int | None = None
    # Generation options
    topic: str = Field(default="", max_length=300)
    style: Literal["light", "balanced", "formal", "detailed", "academic"] = "balanced"
    audience: str = Field(default="", max_length=160)
    research: bool = True
    # 0 means "decide from the brief": a longer brief buys more pages.
    page_count: int = Field(default=0, ge=0, le=12)
    outline: str = Field(default="", max_length=4000)
    language: LanguageCode = "en"
    instructions: str = Field(default="", max_length=4000)


class WikiTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    content_md: str = Field(default="", max_length=100_000)
    keywords: Annotated[list[str], Field(default_factory=list, max_length=20)]


class WikiChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    language: LanguageCode = "en"
    chat_id: int | None = None
    wiki_ids: Annotated[list[int], Field(default_factory=list, max_length=50)]


class AudioRenderIn(BaseModel):
    """Ask for a transcript of one document, in one voice."""

    owner_type: Literal["page", "quiz", "node"]
    owner_id: int = Field(gt=0)
    voice: Literal["female", "male"] = "female"
    # Optional: an instance where the document is written in a language other
    # than its declared one can say so explicitly.
    language: str | None = Field(default=None, max_length=8)
