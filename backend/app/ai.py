# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""AI assistance: quiz generation, translation and moderation reviews.

The provider is any OpenAI-compatible chat completion endpoint (LiteLLM in the
reference deployment). The module is deliberately defensive: every model answer
is parsed, coerced and sanitised by us before it reaches the database, because
model output is untrusted input.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from . import runtime
from .config import settings
from .models import SUPPORTED_LANGUAGES
from .sanitize import html_to_text, sanitize_html, sanitize_plain

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "it": "Italian",
    "es": "Spanish",
    "de": "German",
    "ru": "Russian",
    "zh": "Simplified Chinese",
    "ja": "Japanese",
    "pt": "Portuguese",
    "hi": "Hindi",
    "bn": "Bengali",
    "ar": "Arabic",
}

MAX_TEXT = 500

# Ceiling for the single retry granted to a model that used its whole budget
# on reasoning and returned nothing.
RETRY_TOKEN_CEILING = 8000


class AiError(RuntimeError):
    """Raised when the provider is unavailable or returns unusable content."""


# One message for every provider failure: quota exhausted, model unreachable or
# a malformed answer all look the same to an author, and the difference belongs
# in the administrator's log, not in the interface.
AI_UNAVAILABLE = "AI features are temporarily unavailable. Please try again later."


def is_configured() -> bool:
    return runtime.ai_config().configured


def _headers(config: runtime.AiConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 3000,
    temperature: float = 0.2,
    operation: str = "chat",
) -> str:
    config = runtime.ai_config()
    if not config.configured:
        raise AiError("AI features are disabled on this instance.")
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = config.base_url + "/chat/completions"
    # A reasoning model can spend the whole budget thinking, then answer with an
    # empty string flagged "length". One retry with more room turns a blank
    # "AI unavailable" into the answer the user asked for.
    budgets = [max_tokens]
    if max_tokens < RETRY_TOKEN_CEILING:
        budgets.append(min(max_tokens * 3, RETRY_TOKEN_CEILING))

    data: dict[str, Any] = {}
    response: httpx.Response | None = None
    for index, budget in enumerate(budgets):
        payload["max_tokens"] = budget
        try:
            with httpx.Client(timeout=config.timeout_seconds) as client:
                response = client.post(url, json=payload, headers=_headers(config))
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network dependent
            logger.warning("AI provider returned %s", exc.response.status_code)
            runtime.record_ai_error(
                operation=operation,
                model=config.model,
                base_url=config.base_url,
                status_code=exc.response.status_code,
                detail=exc.response.text or "",
            )
            raise AiError(AI_UNAVAILABLE) from exc
        except (httpx.HTTPError, ValueError) as exc:  # pragma: no cover - network dependent
            logger.warning("AI provider unavailable: %s", exc)
            runtime.record_ai_error(
                operation=operation,
                model=config.model,
                base_url=config.base_url,
                status_code=None,
                detail=str(exc),
            )
            raise AiError(AI_UNAVAILABLE) from exc

        choice = (data.get("choices") or [None])[0] if isinstance(data, dict) else None
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content.strip():
            return content
        truncated = isinstance(choice, dict) and choice.get("finish_reason") == "length"
        if not truncated or index == len(budgets) - 1:
            break

    runtime.record_ai_error(
        operation=operation,
        model=config.model,
        base_url=config.base_url,
        status_code=getattr(response, "status_code", None),
        detail="the model returned an empty answer"
        + (" after exhausting its token budget" if len(budgets) > 1 else ""),
    )
    raise AiError(AI_UNAVAILABLE)


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of a model answer, tolerating markdown fences."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AiError("The AI provider did not return JSON.")
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise AiError("The AI provider returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise AiError("The AI provider returned an unexpected JSON shape.")
    return data


def _json_call(messages: list[dict[str, str]], *, max_tokens: int = 3000, temperature: float = 0.2) -> dict:
    try:
        return _extract_json(_chat(messages, max_tokens=max_tokens, temperature=temperature))
    except AiError:
        # One retry with an explicit reminder: models occasionally wrap or
        # truncate JSON, and a second pass is much cheaper than a failed action.
        nudge = messages + [
            {"role": "user", "content": "Return only a single valid JSON object, no prose, no markdown."}
        ]
        return _extract_json(_chat(nudge, max_tokens=max_tokens, temperature=0.0))


# ---------------------------------------------------------------------------
# Web grounding (optional)
# ---------------------------------------------------------------------------
def web_context(query: str, *, limit: int = 5) -> list[str]:
    """Return short snippets from a SearXNG instance, or [] when unconfigured.

    Grounding is best effort: a search failure must never block generation.
    """
    if not settings.search_base_url:
        return []
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                settings.search_base_url.rstrip("/") + "/search",
                params={"q": query, "format": "json", "language": "en"},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Web grounding skipped: %s", exc)
        return []
    snippets: list[str] = []
    for result in (data.get("results") or [])[:limit]:
        title = sanitize_plain(str(result.get("title") or ""), max_length=120)
        body = sanitize_plain(str(result.get("content") or ""), max_length=400)
        if title or body:
            snippets.append(f"- {title}: {body}".strip())
    return snippets


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
GENERATION_SYSTEM = (
    "You are a meticulous instructional designer who writes exam-grade multiple "
    "choice questions. You always answer with a single JSON object and nothing else."
)


def generate_quiz(
    *,
    topic: str,
    question_count: int,
    mode: str,
    language: str,
    level: str = "",
) -> dict:
    """Ask the model for a complete quiz and return a validated payload."""
    question_count = max(1, min(question_count, settings.ai_max_questions))
    language = language if language in SUPPORTED_LANGUAGES else "en"
    grounding = web_context(topic)
    rules = [
        "Each question has a single unambiguous correct answer set.",
        "Provide 4 options per question unless the topic makes that impossible (min 2, max 8).",
        "At least one option must be wrong.",
        "Option texts are short, plausible and mutually exclusive.",
        "Never invent certifications, version numbers or quotes that do not exist.",
        "Use plain text for options: no HTML, no markdown.",
    ]
    if mode == "swipe":
        rules = [
            "This is a yes/no deck: every question has exactly two options, "
            'the literal texts "Yes" and "No".',
            "Exactly one of them is correct.",
            "Questions must be answerable with yes or no without ambiguity.",
        ]
    prompt = (
        f"Write a quiz about: {topic}\n"
        f"Questions: {question_count}. Difficulty: {level or 'intermediate'}.\n"
        f"Write the content in {LANGUAGE_NAMES[language]}.\n"
        "Rules:\n" + "\n".join(f"- {rule}" for rule in rules) + "\n\n"
    )
    if grounding:
        prompt += "Recent web context (may be incomplete, verify before use):\n" + "\n".join(grounding) + "\n\n"
    prompt += (
        "Answer with this exact shape:\n"
        '{"title": "...", "description": "...", "questions": [{"text": "...", '
        '"time_limit_seconds": 30, "points": 100, "options": [{"text": "...", '
        '"is_correct": true}]}]}\n'
        "The question text must contain no HTML. Return JSON only."
    )
    data = _json_call(
        [
            {"role": "system", "content": GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=min(6000, 400 * question_count + 500),
        temperature=0.4,
    )
    return normalise_generated_quiz(data, mode=mode, fallback_title=topic)


def normalise_generated_quiz(data: dict, *, mode: str, fallback_title: str) -> dict:
    """Coerce model output into a payload the API accepts, or raise AiError."""
    title = sanitize_plain(str(data.get("title") or fallback_title), max_length=120)
    if len(title) < 3:
        title = sanitize_plain(fallback_title, max_length=120) or "Generated quiz"
    description = sanitize_plain(str(data.get("description") or ""), max_length=2000)

    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise AiError("The AI provider did not return any question.")

    questions: list[dict] = []
    for raw in raw_questions[: settings.ai_max_questions]:
        if not isinstance(raw, dict):
            continue
        text = sanitize_plain(str(raw.get("text") or raw.get("text_html") or ""), max_length=2000)
        if not text:
            continue
        raw_options = raw.get("options")
        if not isinstance(raw_options, list):
            continue
        options: list[dict] = []
        for option in raw_options[:8]:
            if not isinstance(option, dict):
                continue
            option_text = sanitize_plain(str(option.get("text") or ""), max_length=MAX_TEXT)
            if not option_text:
                continue
            options.append({"text": option_text, "is_correct": bool(option.get("is_correct"))})
        if mode == "swipe":
            options = [
                {"text": "Yes", "is_correct": bool(next((o["is_correct"] for o in options if o["text"].strip().lower().startswith("y")), True))},
                {"text": "No", "is_correct": bool(next((o["is_correct"] for o in options if o["text"].strip().lower().startswith("n")), False))},
            ]
            if options[0]["is_correct"] == options[1]["is_correct"]:
                options[0]["is_correct"] = True
                options[1]["is_correct"] = False
        options = _dedupe_options(options)
        if len(options) < 2:
            continue
        if not any(option["is_correct"] for option in options):
            options[0]["is_correct"] = True
        if all(option["is_correct"] for option in options):
            options[-1]["is_correct"] = False
        try:
            time_limit = int(raw.get("time_limit_seconds") or 30)
        except (TypeError, ValueError):
            time_limit = 30
        try:
            points = int(raw.get("points") or 100)
        except (TypeError, ValueError):
            points = 100
        questions.append(
            {
                "text_html": sanitize_html(f"<p>{text}</p>"),
                "image_path": None,
                "time_limit_seconds": max(5, min(300, time_limit)),
                "points": max(10, min(1000, points)),
                "options": options,
            }
        )
    if not questions:
        raise AiError("The AI provider produced no usable question.")
    return {"title": title, "description": description, "questions": questions}


def _dedupe_options(options: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for option in options:
        key = option["text"].casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(option)
    return unique


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------
def translate_markdown(text: str, target: str) -> str:
    """Translate a markdown document, keeping its structure and its links.

    Used for the instance legal notice, which is prose an administrator wrote
    and may want in every interface language without retyping it.
    """
    if target not in SUPPORTED_LANGUAGES:
        raise AiError(f"Unsupported target language: {target}")
    body = str(text or "").strip()
    if not body:
        return ""
    prompt = (
        "Translate the following markdown document into "
        f"{LANGUAGE_NAMES[target]} ({target}).\n"
        "Rules:\n"
        "- keep the markdown structure: the same headings, list items, tables, "
        "emphasis and links, in the same order;\n"
        "- translate the link text but never the URL, and never a mail address;\n"
        "- keep proper nouns, product names and licence names as they are "
        "(AGPL-3.0-only, OpenLearn, GDPR);\n"
        "- do not add, remove or summarise anything, and do not wrap the answer "
        "in a code fence;\n"
        "- write plain markdown, the kind a person would type, with no HTML.\n\n"
        f"Document:\n{body}"
    )
    answer = _chat(
        [
            {"role": "system", "content": "You are a professional legal translator."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=min(8000, 1200 + len(body)),
        temperature=0.1,
        operation="legal-translate",
    )
    cleaned = answer.strip()
    # Models like to answer with a fenced block, which would then be stored as
    # part of the notice and shown as a literal code block.
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    if not cleaned:
        raise AiError("The AI provider returned an empty translation.")
    return cleaned


def translate_quiz(quiz: dict, targets: list[str]) -> dict:
    """Translate a quiz payload into ``targets``. Returns ``{lang: translation}``."""
    targets = [lang for lang in targets if lang in SUPPORTED_LANGUAGES]
    if not targets:
        return {}
    requested = ", ".join(f"{lang} ({LANGUAGE_NAMES[lang]})" for lang in targets)
    prompt = (
        "Translate the following quiz faithfully. Keep the meaning, the difficulty, "
        "the technical terms that are usually left untranslated, and the exact same "
        "number of questions and options in the same order.\n"
        f"Target languages: {requested}.\n"
        "Do not add, remove or reorder questions or options. Do not change which "
        "answers are correct.\n\n"
        f"Quiz JSON:\n{json.dumps(quiz, ensure_ascii=False)}\n\n"
        'Answer with: {"translations": {"<lang>": {"title": "...", "description": "...", '
        '"questions": [{"index": 0, "text": "...", "options": [{"index": 0, "text": "..."}]}]}}}\n'
        "Include the html-free text only. Return JSON only."
    )
    data = _json_call(
        [
            {"role": "system", "content": "You are a professional technical translator."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=min(8000, 200 * len(quiz.get("questions", [])) * max(1, len(targets)) + 600),
        temperature=0.1,
    )
    raw = data.get("translations")
    if not isinstance(raw, dict):
        raise AiError("The AI provider did not return translations.")
    result: dict[str, dict] = {}
    for language, payload in raw.items():
        if language not in targets or not isinstance(payload, dict):
            continue
        questions = []
        for entry in payload.get("questions") or []:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("index"))
            except (TypeError, ValueError):
                continue
            text = sanitize_plain(str(entry.get("text") or ""), max_length=2000)
            options = []
            for option in entry.get("options") or []:
                if not isinstance(option, dict):
                    continue
                try:
                    option_index = int(option.get("index"))
                except (TypeError, ValueError):
                    continue
                option_text = sanitize_plain(str(option.get("text") or ""), max_length=MAX_TEXT)
                if option_text:
                    options.append({"index": option_index, "text": option_text})
            if text:
                questions.append({"index": index, "text": text, "options": options})
        result[language] = {
            "title": sanitize_plain(str(payload.get("title") or ""), max_length=120),
            "description": sanitize_plain(str(payload.get("description") or ""), max_length=2000),
            "questions": sorted(questions, key=lambda item: item["index"]),
        }
    if not result:
        raise AiError("The AI provider returned no usable translation.")
    return result


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
SAFETY_POLICY = (
    "Block content that could cause real harm: instructions for weapons, explosives, "
    "drug synthesis, malware or offensive cyber operations, self-harm, sexual content "
    "involving minors, targeted harassment, medical or legal advice presented as fact, "
    "or hateful content against protected groups. Educational questions about these "
    "domains are acceptable only when they teach defence, history, law or safety and do "
    "not provide operational detail."
)


def review_safety(quiz: dict) -> dict:
    """Moderation pass used before a quiz may become public."""
    prompt = (
        "You moderate a public quiz platform.\n"
        f"Policy: {SAFETY_POLICY}\n\n"
        "Review every question and answer set. Flag only real policy violations, not "
        "topics you find unpleasant.\n\n"
        f"Quiz JSON:\n{json.dumps(quiz, ensure_ascii=False)}\n\n"
        'Answer with: {"status": "approved"|"blocked", "summary": "...", '
        '"findings": [{"question_index": 0, "severity": "low"|"medium"|"high", '
        '"issue": "..."}]}\n'
        "status is blocked if any finding is high severity. Return JSON only."
    )
    data = _json_call(
        [
            {"role": "system", "content": "You are a strict but fair content safety reviewer."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
        temperature=0.0,
    )
    status = str(data.get("status") or "").strip().lower()
    if status not in {"approved", "blocked"}:
        status = "blocked" if any(
            str(finding.get("severity", "")).lower() == "high"
            for finding in data.get("findings") or []
            if isinstance(finding, dict)
        ) else "approved"
    findings = []
    for finding in data.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        findings.append(
            {
                "question_index": _safe_int(finding.get("question_index")),
                "severity": sanitize_plain(str(finding.get("severity") or "low"), max_length=10),
                "issue": sanitize_plain(str(finding.get("issue") or ""), max_length=300),
            }
        )
    return {
        "status": status,
        "summary": sanitize_plain(str(data.get("summary") or ""), max_length=600),
        "findings": findings[:50],
    }


def review_answers(quiz: dict) -> dict:
    """Fact-check a quiz: wrong official answers, ambiguity, duplicates."""
    prompt = (
        "You review quiz answer keys for correctness.\n"
        "For each question check that (1) the marked correct answer(s) are actually "
        "correct, (2) no other option is also correct, (3) the wording is unambiguous, "
        "(4) multi-answer questions expect exactly the marked set.\n"
        "Be strict about facts. If the answer key is wrong, provide the corrected "
        "question and its full option list with is_correct flags.\n\n"
        f"Quiz JSON:\n{json.dumps(quiz, ensure_ascii=False)}\n\n"
        'Answer with: {"status": "ok"|"corrected", "summary": "...", '
        '"findings": [{"question_index": 0, "severity": "low"|"medium"|"high", '
        '"issue": "..."}], "corrections": [{"question_index": 0, "text": "...", '
        '"options": [{"text": "...", "is_correct": true}]}]}\n'
        "Use the same language as the quiz. Return JSON only."
    )
    data = _json_call(
        [
            {"role": "system", "content": "You are a subject matter expert and exam reviewer."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4000,
        temperature=0.0,
    )
    status = str(data.get("status") or "").strip().lower()
    corrections = []
    for entry in data.get("corrections") or []:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("question_index"))
        except (TypeError, ValueError):
            continue
        options = []
        for option in entry.get("options") or []:
            if not isinstance(option, dict):
                continue
            text = sanitize_plain(str(option.get("text") or ""), max_length=MAX_TEXT)
            if text:
                options.append({"text": text, "is_correct": bool(option.get("is_correct"))})
        options = _dedupe_options(options)
        text = sanitize_plain(str(entry.get("text") or ""), max_length=2000)
        if text and len(options) >= 2:
            corrections.append({"question_index": index, "text": text, "options": options})
    if status not in {"ok", "corrected"}:
        status = "corrected" if corrections else "ok"
    if corrections:
        status = "corrected"
    findings = []
    for finding in data.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        findings.append(
            {
                "question_index": _safe_int(finding.get("question_index")),
                "severity": sanitize_plain(str(finding.get("severity") or "low"), max_length=10),
                "issue": sanitize_plain(str(finding.get("issue") or ""), max_length=300),
            }
        )
    return {
        "status": status,
        "summary": sanitize_plain(str(data.get("summary") or ""), max_length=600),
        "findings": findings[:50],
        "corrections": corrections[: settings.ai_max_questions],
    }


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def text_plain(html: str) -> str:
    return html_to_text(html)
