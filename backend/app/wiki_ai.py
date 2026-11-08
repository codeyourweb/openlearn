# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""AI assistance for the wiki: sourced generation, reviews and RAG chat.

Everything here is written for a *reasonable* model — a 30B-class model behind an
OpenAI-compatible endpoint (gemma 31B on Ollama, 65k of context in the reference
deployment). That constraint drives the design:

* generation is *staged*: one cheap call for an outline, then one call per page,
  each one fed only the sources it needs. A single prompt asking for a whole
  wiki would blow the context and the quality;
* every web result is numbered once and cited by number, so the reader can check
  the claim instead of trusting the prose;
* retrieval for the chat is lexical (SQLite FTS5 + BM25) and capped: the model
  never sees more than a handful of chunks, whatever the size of the corpus;
* the model's output is untrusted input: it is parsed, clamped and sanitised
  before it reaches the database, and it never decides who may read a page.

Long jobs run in the background and are polled through ``GET /wiki/ai/jobs/{id}``;
one job of a given kind and target can exist at a time (see
``claim_job``), which is what keeps a shared provider from being hammered.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

import httpx

from . import runtime
from .config import settings
from .db import SessionLocal
from .models import AiJob, User, Wiki, WikiPage, utcnow
from .sanitize import sanitize_plain
from .search import fts_any_query, keywords
from .wiki import reflow_markdown

logger = logging.getLogger(__name__)

# How much text one page should carry, per writing style.
STYLES: dict[str, dict[str, object]] = {
    "light": {
        "label": "Light",
        "words": 250,
        "research": 2,
        "tone": "short, friendly notes: one idea per paragraph, bullet points welcome",
    },
    "balanced": {
        "label": "Balanced",
        "words": 600,
        "research": 4,
        "tone": "clear and neutral, with a short introduction and a closing takeaway",
    },
    "formal": {
        "label": "Formal",
        "words": 700,
        "research": 4,
        "tone": "impersonal and precise, no exclamation marks, complete sentences",
    },
    "detailed": {
        "label": "Detailed",
        "words": 1200,
        "research": 6,
        "tone": "in-depth, examples and edge cases, sub-sections with ## headings",
    },
    "academic": {
        "label": "Academic",
        "words": 1100,
        "research": 8,
        "tone": "structured like a course chapter: definitions, method, limits, further reading",
    },
}

LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "it": "Italian",
    "es": "Spanish",
    "de": "German",
    "zh": "Simplified Chinese",
    "ja": "Japanese",
}


class AiUnavailable(RuntimeError):
    """The provider is missing, unreachable or answered something unusable."""


# ---------------------------------------------------------------------------
# Provider plumbing (shared with the quiz side, duplicated on purpose: the quiz
# prompts and this pipeline have diverged enough that sharing would couple them)
# ---------------------------------------------------------------------------
AI_UNAVAILABLE = "AI features are temporarily unavailable. Please try again later."


def is_configured() -> bool:
    return runtime.ai_config().configured


def _chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 2400,
    temperature: float = 0.3,
    operation: str = "wiki",
) -> str:
    config = runtime.ai_config()
    if not config.configured:
        raise AiUnavailable("AI features are disabled on this instance.")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.wiki_model_or_default,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = config.base_url + "/chat/completions"
    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:  # pragma: no cover - network dependent
        logger.warning("wiki AI provider returned %s", exc.response.status_code)
        runtime.record_ai_error(
            operation=operation,
            model=config.wiki_model_or_default,
            base_url=config.base_url,
            status_code=exc.response.status_code,
            detail=exc.response.text or "",
        )
        raise AiUnavailable(AI_UNAVAILABLE) from exc
    except (httpx.HTTPError, ValueError) as exc:  # pragma: no cover - network dependent
        logger.warning("wiki AI provider unavailable: %s", exc)
        runtime.record_ai_error(
            operation=operation,
            model=config.wiki_model_or_default,
            base_url=config.base_url,
            status_code=None,
            detail=str(exc),
        )
        raise AiUnavailable(AI_UNAVAILABLE) from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - provider specific
        runtime.record_ai_error(
            operation=operation,
            model=config.wiki_model_or_default,
            base_url=config.base_url,
            status_code=getattr(response, "status_code", None),
            detail="unexpected provider payload",
        )
        raise AiUnavailable(AI_UNAVAILABLE) from exc
    if not isinstance(content, str) or not content.strip():
        raise AiUnavailable(AI_UNAVAILABLE)
    return content


def _json_call(messages: list[dict[str, str]], *, max_tokens: int = 2000) -> dict:
    raw = _chat(messages, max_tokens=max_tokens, temperature=0.2)
    cleaned = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AiUnavailable("The AI provider did not return JSON.")
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise AiUnavailable("The AI provider returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise AiUnavailable("The AI provider returned an unexpected JSON shape.")
    return data


# ---------------------------------------------------------------------------
# Web research
# ---------------------------------------------------------------------------
def searxng(query: str, *, limit: int = 6, language: str = "en") -> list[dict[str, str]]:
    """Numbered web results from the SearXNG instance of the stack, or [].

    Research is best effort by design: a search failure degrades the sourcing of
    a page, it never fails the job.
    """
    if not settings.search_base_url:
        return []
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                settings.search_base_url.rstrip("/") + "/search",
                params={"q": query, "format": "json", "language": language, "safesearch": 1},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("wiki research skipped: %s", exc)
        return []
    results: list[dict[str, str]] = []
    for item in (data.get("results") or [])[:limit]:
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        results.append(
            {
                "title": sanitize_plain(str(item.get("title") or url), max_length=160),
                "url": url[:400],
                "snippet": sanitize_plain(str(item.get("content") or ""), max_length=400),
            }
        )
    return results


def gather_sources(topic: str, *, style: str, language: str, extra_queries: list[str] | None = None) -> list[dict[str, str]]:
    """Search for the topic, then for its natural sub-questions."""
    wanted = int(STYLES.get(style, STYLES["balanced"])["research"])  # type: ignore[arg-type]
    queries = [topic] + list(extra_queries or [])
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    for query in queries:
        if len(collected) >= wanted * 2:
            break
        for result in searxng(query, limit=wanted, language=language):
            if result["url"] in seen:
                continue
            seen.add(result["url"])
            collected.append(result)
    return collected[: wanted * 2]


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
_FOOTNOTE_DEF = re.compile(r"^\[\^(\d{1,3})\]:", re.MULTILINE)
_INLINE_CITATION = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")


def normalise_citations(markdown: str, sources: list[dict[str, str]]) -> str:
    """Turn ``[n]`` markers into markdown footnotes pointing at real URLs.

    The model is asked to cite with footnote syntax, but small models drift: this
    rewrites bare ``[n]`` markers and appends the definitions that are missing, so
    a citation always resolves to a source or disappears.
    """
    if not sources:
        return markdown
    limit = len(sources)

    def inline(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return f"[^{index}]" if 1 <= index <= limit else match.group(0)

    text = _INLINE_CITATION.sub(inline, markdown or "")
    defined = {int(number) for number in _FOOTNOTE_DEF.findall(text)}
    used = {int(number) for number in re.findall(r"\[\^(\d{1,3})\](?!:)", text)}
    missing = sorted(number for number in used - defined if 1 <= number <= limit)
    if missing:
        text = text.rstrip() + "\n\n"
        for number in missing:
            source = sources[number - 1]
            text += f"[^{number}]: [{source['title']}]({source['url']})\n"
    return text


def source_block(sources: list[dict[str, str]]) -> str:
    """Compact numbered list handed to the model as the only allowed evidence."""
    lines = []
    for index, source in enumerate(sources, start=1):
        snippet = source.get("snippet") or ""
        lines.append(f"[{index}] {source['title']} — {source['url']}\n    {snippet}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
OUTLINE_SYSTEM = (
    "You are a senior technical writer planning a knowledge base. You answer with "
    "a single JSON object and nothing else."
)


def plan_outline(
    *,
    topic: str,
    page_count: int,
    style: str,
    audience: str,
    language: str,
    sources: list[dict[str, str]],
    instructions: str = "",
) -> list[dict[str, object]]:
    style_spec = STYLES.get(style, STYLES["balanced"])
    prompt = (
        f"Plan a wiki of {page_count} pages about: {topic}\n"
        f"Audience: {audience or 'curious adults with no prior knowledge'}.\n"
        f"Writing style: {style_spec['label']} — {style_spec['tone']}.\n"
        f"Write titles and summaries in {LANGUAGE_NAMES.get(language, 'English')}.\n"
        "Cover the subject in a sensible reading order: an overview page first, "
        "then the pages a reader needs next. No page may duplicate another.\n"
    )
    if instructions:
        prompt += f"Author instructions: {instructions}\n"
    if sources:
        prompt += (
            "Available sources (you will cite them while writing, not here):\n"
            + source_block(sources[:12])
            + "\n"
        )
    prompt += (
        'Answer with {"pages": [{"title": "...", "summary": "...", '
        '"points": ["...", "..."]}]}. Return JSON only.'
    )
    data = _json_call(
        [
            {"role": "system", "content": OUTLINE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1400,
    )
    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise AiUnavailable("The AI provider did not return an outline.")
    pages: list[dict[str, object]] = []
    for raw in raw_pages[:page_count]:
        if not isinstance(raw, dict):
            continue
        title = sanitize_plain(str(raw.get("title") or ""), max_length=120)
        if not title:
            continue
        summary = sanitize_plain(str(raw.get("summary") or ""), max_length=600)
        points = [
            sanitize_plain(str(point), max_length=200)
            for point in (raw.get("points") or [])[:8]
            if str(point).strip()
        ]
        pages.append({"title": title, "summary": summary, "points": points})
    if not pages:
        raise AiUnavailable("The AI provider returned an unusable outline.")
    return pages


PAGE_SYSTEM = (
    "You are a rigorous encyclopedia writer. You write markdown, cite every factual "
    "claim, and never invent a source. You answer with the page body only."
)


def write_page(
    *,
    topic: str,
    page: dict[str, object],
    style: str,
    audience: str,
    language: str,
    sources: list[dict[str, str]],
    prior_titles: list[str],
    instructions: str = "",
) -> str:
    style_spec = STYLES.get(style, STYLES["balanced"])
    words = int(style_spec["words"])  # type: ignore[arg-type]
    prompt = (
        f"Write the wiki page «{page['title']}» of a knowledge base about {topic}.\n"
        f"Summary to cover: {page.get('summary') or ''}\n"
        f"Points to include: {', '.join(page.get('points') or []) or 'as you see fit'}\n"
        f"Audience: {audience or 'curious adults'}. Style: {style_spec['label']} "
        f"({style_spec['tone']}). Length: about {words} words.\n"
        f"Language: {LANGUAGE_NAMES.get(language, 'English')}.\n"
    )
    if instructions:
        prompt += (
            "The author asked for this, follow it page by page and do not drift "
            f"from it: {instructions}\n"
        )
    prompt += (
        "Format: markdown. Start with a level-1 heading, use ## for sections, "
        "lists and tables where they help. Do not repeat these pages: "
        f"{', '.join(prior_titles) or 'none yet'}.\n"
    )
    if sources:
        prompt += (
            "Cite every factual claim with a footnote marker like [^1] and use only "
            "these sources, by their number:\n"
            + source_block(sources)
            + "\n"
            "Never cite a number that is not in the list. Never write the footnote "
            "definitions yourself, they are appended automatically.\n"
        )
    else:
        prompt += (
            "No web source is available: write general knowledge only, and add the "
            "sentence 'This page was written without external sources.' at the end.\n"
        )
    prompt += "Return the markdown body only, no code fence, no commentary."
    body = _chat(
        [
            {"role": "system", "content": PAGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=min(4000, 6 * words + 400),
        temperature=0.35,
    )
    body = body.strip()
    body = re.sub(r"^```(?:markdown|md)?\s*", "", body)
    body = re.sub(r"```$", "", body).strip()
    if not body.startswith("#"):
        body = f"# {page['title']}\n\n{body}"
    return normalise_citations(body, sources)


def review_page(page: dict[str, str], *, language: str, kind: str) -> dict:
    """Grammar, legality or compliance pass over one page.

    Returns ``{status, summary, findings[], corrected_markdown?}`` where status is
    ``ok``, ``warn`` or ``blocked``.
    """
    labels = {
        "grammar": (
            "Correct spelling, grammar and punctuation. Keep the markdown structure, "
            "the citations and the meaning. Never add facts."
        ),
        "compliance": (
            "Check regulatory and policy compliance for a public knowledge base: "
            "personal data, medical or legal advice, unverified claims. Flag every "
            "problem with the exact sentence."
        ),
        "review": (
            "Review this page for a public knowledge base: factual accuracy, "
            "unsupported claims, tone, structure and legibility. Flag what a reader "
            "could misread."
        ),
    }
    instruction = labels.get(kind, labels["review"])
    prompt = (
        f"Task: {instruction}\n"
        # The wiki's default language is where the *interface* speaks, not proof
        # of what the page says: without this line a grammar pass on a French
        # page of an English-default wiki came back translated, and the pass
        # writes its answer back into the page.
        f"The wiki is configured for {LANGUAGE_NAMES.get(language, 'English')}. "
        "Never translate: correct the page in the language it is actually written in, "
        "and keep that language.\n"
        "Answer with JSON only:\n"
        '{"status": "ok|warn|blocked", "summary": "...", "findings": '
        '[{"severity": "info|warn|error", "quote": "...", "issue": "...", "fix": "..."}], '
        '"corrected_markdown": "..."}\n'
        "Include corrected_markdown only when you rewrote the page, and keep all "
        "footnote markers untouched.\n\n---\n"
        f"{page.get('content_md', '')[:24_000]}"
    )
    data = _json_call(
        [
            {"role": "system", "content": "You are a meticulous editor. JSON only."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=3000,
    )
    status = str(data.get("status") or "warn").lower()
    if status not in {"ok", "warn", "blocked"}:
        status = "warn"
    findings = []
    for raw in (data.get("findings") or [])[:20]:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity") or "info").lower()
        findings.append(
            {
                "severity": severity if severity in {"info", "warn", "error"} else "info",
                "quote": sanitize_plain(str(raw.get("quote") or ""), max_length=300),
                "issue": sanitize_plain(str(raw.get("issue") or ""), max_length=400),
                "fix": sanitize_plain(str(raw.get("fix") or ""), max_length=400),
            }
        )
    corrected = data.get("corrected_markdown")
    return {
        "status": status,
        "summary": sanitize_plain(str(data.get("summary") or ""), max_length=600),
        "findings": findings,
        "corrected_markdown": corrected if isinstance(corrected, str) and corrected.strip() else "",
    }


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------
def chunk_markdown(markdown: str, *, size: int = 1200) -> list[dict[str, str]]:
    """Split a page on headings, then on paragraphs, into citation-sized chunks."""
    chunks: list[dict[str, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            chunks.append({"heading": heading, "text": text[:size]})
        buffer.clear()

    for line in (markdown or "").splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            continue
        buffer.append(line)
        if sum(len(part) for part in buffer) > size:
            flush()
    flush()
    return chunks


def retrieve(db, question: str, wiki_ids: list[int], *, limit: int = 6) -> list[dict[str, object]]:
    """Best chunks for the question, scoped to the wikis the reader may open."""
    if not wiki_ids:
        return []
    expression = fts_any_query(question)
    rows = []
    # FTS5 only exists in SQLite; elsewhere the LIKE fallback below is the
    # normal path, not an error worth logging on every question.
    bind = db.get_bind()
    fts_available = bind is not None and bind.dialect.name == "sqlite"
    if expression and fts_available:
        try:
            rows = db.execute(
                __import__("sqlalchemy").text(
                    "SELECT p.id, bm25(wiki_pages_fts, 3.0, 1.0) AS score "
                    "FROM wiki_pages_fts f JOIN wiki_pages p ON p.id = f.rowid "
                    "WHERE wiki_pages_fts MATCH :q "
                    "AND p.wiki_id IN (" + ",".join(str(int(i)) for i in wiki_ids[:100]) + ") "
                    "ORDER BY score LIMIT 12"
                ),
                {"q": expression},
            ).all()
        except Exception as exc:  # noqa: BLE001 - FTS missing or query refused
            logger.info("RAG FTS unavailable: %s", exc)
            rows = []
    if not rows:
        pages = db.execute(
            __import__("sqlalchemy").text(
                "SELECT id, 0 FROM wiki_pages WHERE wiki_id IN ("
                + ",".join(str(int(i)) for i in wiki_ids[:100])
                + ") AND (title LIKE :like OR content_md LIKE :like) LIMIT 12"
            ),
            {"like": f"%{question[:60]}%"},
        ).all()
        rows = pages

    results: list[dict[str, object]] = []
    for page_id, score in rows:
        page = db.get(WikiPage, page_id)
        if page is None:
            continue
        best = None
        wanted = {token.lower() for token in keywords(question)}
        for chunk in chunk_markdown(page.content_md):
            overlap = len(wanted & set(chunk["text"].lower().split()))
            if best is None or overlap > best[0]:
                best = (overlap, chunk)
        if best is None:
            continue
        wiki = db.get(Wiki, page.wiki_id)
        results.append(
            {
                "page_id": page.id,
                "wiki_id": page.wiki_id,
                "wiki_title": wiki.title if wiki else "",
                "title": page.title,
                "slug": page.slug,
                "heading": best[1]["heading"],
                "text": best[1]["text"],
                "score": round(float(score), 4),
            }
        )
        if len(results) >= limit:
            break
    return results


_NOTHING_FOUND = {
    "fr": "Je ne trouve rien là-dessus dans les wikis que vous pouvez lire. Essayez "
          "d'autres mots, ou ouvrez un wiki qui traite du sujet.",
    "en": "I found nothing about that in the wikis you can read. Try other words, or "
          "open a wiki that covers the subject.",
    "de": "Dazu finde ich in den Wikis, die Sie lesen können, nichts. Versuchen Sie "
          "andere Wörter oder öffnen Sie ein Wiki zu diesem Thema.",
    "es": "No encuentro nada sobre eso en los wikis que puede leer. Pruebe otras "
          "palabras o abra un wiki que trate el tema.",
    "it": "Non trovo nulla su questo nei wiki che può leggere. Provi altre parole o "
          "apra un wiki che tratti l'argomento.",
    "ja": "閲覧できるウィキには該当する内容が見つかりませんでした。別の言葉で試すか、"
          "その話題を扱うウィキを開いてください。",
    "zh": "在您可阅读的维基中没有找到相关内容。请换用其他词语，或打开涉及该主题的维基。",
}


def _nothing_found(language: str) -> str:
    return _NOTHING_FOUND.get(language, _NOTHING_FOUND["en"])


def answer_question(
    db, *, question: str, wiki_ids: list[int], language: str = "en"
) -> tuple[str, list[dict[str, object]]]:
    """Grounded answer plus the sources it was allowed to use."""
    chunks = retrieve(db, question, wiki_ids)
    if not chunks:
        return (_nothing_found(language), [])
    context_lines = []
    sources = []
    for index, chunk in enumerate(chunks, start=1):
        context_lines.append(
            f"[{index}] {chunk['wiki_title']} — {chunk['title']}"
            + (f" — {chunk['heading']}" if chunk["heading"] else "")
            + f"\n{chunk['text']}\n"
        )
        sources.append(
            {
                "n": index,
                "page_id": chunk["page_id"],
                "wiki_id": chunk["wiki_id"],
                "wiki_title": chunk["wiki_title"],
                "title": chunk["title"],
                "slug": chunk["slug"],
                "heading": chunk["heading"],
                "snippet": str(chunk["text"])[:240],
            }
        )
    prompt = (
        "Answer the question using ONLY the numbered extracts below. If they do not "
        "contain the answer, say so plainly instead of guessing. Cite the extracts "
        "you used with their number in brackets, like this: [2].\n"
        f"Answer in {LANGUAGE_NAMES.get(language, 'English')}. Be concise (max 250 words).\n\n"
        f"Question: {question}\n\n"
        "Extracts:\n" + "\n".join(context_lines)
    )
    answer = _chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a retrieval assistant. You never use knowledge outside "
                    "the extracts, you always cite, and you say when the extracts are "
                    "silent."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
        temperature=0.15,
    )
    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", answer)}
    sources = [source for source in sources if int(source["n"]) in cited] or sources
    return answer.strip(), sources


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def claim_job(db, *, user: User, kind: str, key: str, target_type: str = "wiki", target_id: int | None = None, payload: dict | None = None) -> AiJob:
    """Create a job, or refuse because an identical one is still working.

    The uniqueness gate lives in the database so it survives a restart, and it is
    scoped to the *task* rather than the user: two authors asking for the same
    generation must not pay for it twice.
    """
    existing = (
        db.query(AiJob)
        .filter(AiJob.key == key, AiJob.status.in_(("queued", "running")))
        .first()
    )
    if existing is not None:
        raise JobConflict(existing.id)
    job = AiJob(
        user_id=user.id,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        key=key,
        payload=payload or {},
        status="queued",
        message="Queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class JobConflict(RuntimeError):
    def __init__(self, job_id: int) -> None:
        super().__init__("A job of the same kind is already running.")
        self.job_id = job_id


def _progress(db, job: AiJob, value: int, message: str) -> None:
    job.progress = max(0, min(value, 100))
    job.message = message[:300]
    db.commit()


def run_job(job_id: int) -> None:
    """Entry point of the background task: never raises into the event loop."""
    with SessionLocal() as db:
        job = db.get(AiJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = utcnow()
        db.commit()
        try:
            if job.kind == "generate":
                result = _run_generate(db, job)
            elif job.kind in {"review", "grammar", "compliance"}:
                result = _run_review(db, job)
            elif job.kind == "expand":
                result = _run_generate(db, job, append=True)
            elif job.kind == "fill":
                result = _run_fill(db, job)
            else:
                raise AiUnavailable(f"Unknown job kind: {job.kind}.")
            job.result = result
            job.status = "done"
            job.progress = 100
            job.message = "Done"
        except (AiUnavailable, ValueError) as exc:
            db.rollback()
            job = db.get(AiJob, job_id)
            job.status = "error"
            job.error = str(exc)[:2000]
            job.message = "Failed"
        except Exception as exc:  # noqa: BLE001 - a background task must not crash
            logger.exception("wiki AI job %s failed", job_id)
            db.rollback()
            job = db.get(AiJob, job_id)
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
            job.message = "Failed"
        finally:
            job.finished_at = utcnow()
            db.commit()


def _run_generate(db, job: AiJob, *, append: bool = False) -> dict:
    payload = job.payload or {}
    topic = sanitize_plain(str(payload.get("topic") or ""), max_length=300)
    if not topic:
        raise AiUnavailable("A topic is required.")
    style = str(payload.get("style") or "balanced")
    language = str(payload.get("language") or "en")
    audience = sanitize_plain(str(payload.get("audience") or ""), max_length=160)
    instructions = sanitize_plain(str(payload.get("instructions") or ""), max_length=4000)
    page_count = int(payload.get("page_count") or 0)
    if page_count <= 0:
        # The brief is the contract: a paragraph asking for depth gets more
        # pages than a two-word topic.
        page_count = max(3, min(8, 2 + len(instructions) // 300))
    research = bool(payload.get("research", True))

    _progress(db, job, 5, "Researching sources")
    sources = gather_sources(topic, style=style, language=language) if research else []
    _progress(db, job, 15, f"{len(sources)} sources found, planning the outline")

    outline = plan_outline(
        topic=topic,
        page_count=page_count,
        style=style,
        audience=audience,
        language=language,
        sources=sources,
        instructions=instructions,
    )
    _progress(db, job, 25, f"Outline ready: {len(outline)} pages")

    wiki = db.get(Wiki, job.target_id) if job.target_id else None
    if wiki is None:
        raise AiUnavailable("The target wiki no longer exists.")
    existing_titles = [page.title for page in db.query(WikiPage).filter(WikiPage.wiki_id == wiki.id)]
    created: list[dict[str, object]] = []
    for index, plan in enumerate(outline):
        _progress(db, job, 25 + int(65 * (index / max(1, len(outline)))), f"Writing «{plan['title']}»")
        body = write_page(
            topic=topic,
            page=plan,
            style=style,
            audience=audience,
            language=language,
            sources=sources,
            prior_titles=existing_titles,
            instructions=instructions,
        )
        if sources:
            body += "\n\n" + "\n".join(
                f"[^{number}]: [{source['title']}]({source['url']})"
                for number, source in enumerate(sources, start=1)
                if f"[^{number}]" in body
            )
        title = str(plan["title"])
        taken = set(db.scalars(__import__("sqlalchemy").select(WikiPage.slug).where(WikiPage.wiki_id == wiki.id)).all())
        from .wiki import slugify, unique_slug

        page = WikiPage(
            wiki_id=wiki.id,
            slug=unique_slug(slugify(title, fallback="page"), taken),
            title=title,
            content_md=reflow_markdown(body).strip(),
            tags=[topic.lower()[:40]],
            position=len(existing_titles),
            author_id=job.user_id,
        )
        db.add(page)
        db.flush()
        from .routers.wiki import _freeze, _rebuild_links

        _freeze(db, page, db.get(User, job.user_id), note="Generated by AI")
        _rebuild_links(db, page)
        db.commit()
        existing_titles.append(title)
        created.append({"page_id": page.id, "title": title, "slug": page.slug, "version": page.current_version_number})

    _progress(db, job, 95, "Finished")
    return {
        "wiki_id": wiki.id,
        "topic": topic,
        "style": style,
        "pages": created,
        "sources": sources,
        "research": research,
    }


def _run_fill(db, job: AiJob) -> dict:
    """Write one page's body for an editor that is already open.

    Nothing is stored: the caller gets the markdown and drops it into the
    editing surface, so an author can read, cut and rewrite before saving.
    """
    payload = job.payload or {}
    title = sanitize_plain(str(payload.get("topic") or ""), max_length=200)
    if not title:
        raise AiUnavailable("A title is required.")
    style = str(payload.get("style") or "balanced")
    language = str(payload.get("language") or "en")
    audience = sanitize_plain(str(payload.get("audience") or ""), max_length=160)
    instructions = sanitize_plain(str(payload.get("instructions") or ""), max_length=4000)
    research = bool(payload.get("research", True))

    _progress(db, job, 10, "Researching sources" if research else "Preparing the page")
    sources = gather_sources(title, style=style, language=language) if research else []
    _progress(db, job, 45, "Writing")
    body = write_page(
        topic=title,
        page={"title": title, "summary": instructions[:400], "points": []},
        style=style,
        audience=audience,
        language=language,
        sources=sources,
        prior_titles=[],
        instructions=instructions,
    )
    if sources:
        body += "\n\n" + "\n".join(
            f"[^{number}]: [{source['title']}]({source['url']})"
            for number, source in enumerate(sources, start=1)
            if f"[^{number}]" in body
        )
    _progress(db, job, 95, "Finished")
    return {"title": title, "content_md": reflow_markdown(body).strip(), "sources": sources}


def _run_review(db, job: AiJob) -> dict:
    payload = job.payload or {}
    page_id = int(payload.get("page_id") or 0)
    page = db.get(WikiPage, page_id)
    if page is None:
        raise AiUnavailable("The page no longer exists.")
    wiki = db.get(Wiki, page.wiki_id)
    if wiki is None:
        raise AiUnavailable("The page does not belong to that wiki.")
    # `target_id` names the page for a page-scoped job and the wiki otherwise.
    # The first version compared it to the wiki id in both cases, so every
    # grammar or compliance pass died with "The page does not belong to that
    # wiki" — except on the home page of a wiki, whose id happens to equal its
    # wiki's. That coincidence is why the bug survived the first tests.
    if job.target_type == "page":
        if job.target_id and job.target_id != page.id:
            raise AiUnavailable("The page does not belong to that wiki.")
    elif job.target_id and job.target_id != wiki.id:
        raise AiUnavailable("The page does not belong to that wiki.")
    if payload.get("wiki_id") and int(payload["wiki_id"]) != wiki.id:
        raise AiUnavailable("The page does not belong to that wiki.")
    _progress(db, job, 20, f"Reviewing «{page.title}»")
    review = review_page(
        {"title": page.title, "content_md": page.content_md},
        language=str(payload.get("language") or wiki.default_language or "en"),
        kind=job.kind,
    )
    corrected = review.pop("corrected_markdown", "")
    applied = False
    if corrected and job.kind == "grammar" and bool(payload.get("apply", True)):
        page.content_md = normalise_citations(corrected, [])
        from .routers.wiki import _freeze, _rebuild_links

        _freeze(db, page, db.get(User, job.user_id), note="Grammar pass applied")
        _rebuild_links(db, page)
        db.commit()
        applied = True
    return {"page_id": page.id, "kind": job.kind, "applied": applied, **review}


def stale_jobs(db) -> int:
    """Mark jobs left running by a crash as failed, once, at boot."""
    now = datetime.now(UTC)
    count = 0
    for job in db.query(AiJob).filter(AiJob.status.in_(("queued", "running"))).all():
        job.status = "error"
        job.error = "Interrupted by a restart."
        job.finished_at = now
        count += 1
    if count:
        db.commit()
    return count


# ---------------------------------------------------------------------------
# Tags and quizzes built from a wiki
# ---------------------------------------------------------------------------

TAG_SYSTEM = (
    "You label documentation pages. You answer with strict JSON and nothing else: "
    '{"tags": ["...", "..."]}. Tags are lowercase, 1 to 3 words, no punctuation, '
    "no hashtag, at most 8 of them, and they describe the subject rather than the format."
)


def suggest_tags(
    title: str,
    body: str,
    *,
    language: str = "en",
    existing: list[str] | None = None,
) -> list[str]:
    """Propose subject tags for one page; the author decides what to keep."""
    if not is_configured():
        raise RuntimeError("AI is not configured.")
    messages = [
        {"role": "system", "content": TAG_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Language for the tags: {language}\n"
                f"Categories already used in this wiki (reuse one when it fits): "
                f"{', '.join((existing or [])[:40]) or 'none'}\n\n"
                f"# {title}\n\n{body[:6000]}"
            ),
        },
    ]
    data = _json_call(messages, max_tokens=400)
    tags = data.get("tags") if isinstance(data, dict) else None
    cleaned: list[str] = []
    if isinstance(tags, list):
        for value in tags:
            if not isinstance(value, str):
                continue
            tag = re.sub(r"[^\w\sÀ-ÿ-]", "", value.strip().lower()).strip()
            tag = re.sub(r"\s+", " ", tag)[:40]
            if tag and tag not in cleaned:
                cleaned.append(tag)
    return cleaned[:8]


QUIZ_SYSTEM = (
    "You write questionnaires from source documentation. You answer with strict JSON "
    "and nothing else, shaped like:\n"
    '{"title": "...", "description": "...", "questions": [{"text": "...", '
    '"options": [{"text": "...", "correct": true}], "explanation": "..."}]}\n'
    "Every question must be answerable from the source only. Never invent facts, "
    "figures or names that the source does not state. Options are short."
)


def quiz_from_pages(
    wiki_title: str,
    pages: list[dict[str, str]],
    *,
    mode: str = "qcm",
    count: int = 8,
    language: str = "en",
    brief: str = "",
) -> dict:
    """Build a questionnaire from wiki content, ready to store as a real quiz."""
    if not is_configured():
        raise RuntimeError("AI is not configured.")
    source = "\n\n".join(
        f"## {page['title']}\n\n{(page.get('content_md') or '')[:2500]}" for page in pages
    )[:14000]
    if mode == "swipe":
        shape = (
            "Build swipe cards: each question is a statement about the subject, with exactly "
            "two options, 'Yes' first and 'No' second, and `correct` true on the one that the "
            "source supports."
        )
    else:
        shape = (
            "Build multiple-choice questions: four options, one to three of them correct, "
            "`correct` set on each right one. Wrong options must be plausible but clearly "
            "contradicted by the source."
        )
    messages = [
        {"role": "system", "content": QUIZ_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Language of the questionnaire: {language}\n"
                f"Number of questions: exactly {count}\n"
                f"{shape}\n"
                f"Extra instructions: {brief or 'none'}\n\n"
                f"Wiki: {wiki_title}\n\nSource pages:\n{source}"
            ),
        },
    ]
    data = _json_call(messages, max_tokens=max(1200, count * 260))
    if not isinstance(data, dict):
        raise RuntimeError("The model did not return a questionnaire.")

    questions: list[dict] = []
    for raw in (data.get("questions") or [])[:count]:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()[:500]
        options = []
        for option in (raw.get("options") or [])[:8]:
            if not isinstance(option, dict):
                continue
            label = str(option.get("text") or "").strip()[:300]
            if label:
                options.append({"text": label, "correct": bool(option.get("correct"))})
        if not text or len(options) < 2:
            continue
        if mode == "swipe":
            options = options[:2]
            if not any(option["correct"] for option in options):
                options[0]["correct"] = True
        elif not any(option["correct"] for option in options):
            # A scored question without a key would be unplayable: skip it.
            continue
        questions.append(
            {
                "text": text,
                "options": options,
                "explanation": str(raw.get("explanation") or "").strip()[:600],
            }
        )
    if not questions:
        raise RuntimeError("The model returned no usable question.")
    return {
        "title": str(data.get("title") or wiki_title).strip()[:120] or wiki_title,
        "description": str(data.get("description") or "").strip()[:500],
        "questions": questions,
    }
