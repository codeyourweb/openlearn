# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Speech transcripts of the reading content, produced at editing time.

The rules this module implements:

* audio is generated when the author asks for it, never while a reader waits;
* one synthesis at a time, because a small box cannot decode two models;
* the same paragraph is never paid for twice — segments are cached on the exact
  text, voice and language that produced them;
* a document edited after its transcript was made shows no player at all, so
  nobody listens to a text that is no longer on the page.
"""

from __future__ import annotations

import hashlib
import html
import re
import secrets
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .models import AiJob, AudioRendition, AudioSegment, Quiz, Wiki, WikiPage

# Audio seconds produced per second of CPU, measured on an eight-core box with
# no GPU: 410 characters gave 26.7 s of audio in 99 s. The UI turns this into
# the "about N minutes" line, and the character ceiling is set from it.
CPU_SECONDS_PER_AUDIO_SECOND = 3.7
# Characters per second of speech, same measurement: 410 characters, 26.7 s.
CHARS_PER_AUDIO_SECOND = 15.4

VOICES = ("female", "male")

# How the narrator carries the text. A wiki article and a children's adventure
# read the same sentence differently, so this is chosen per transcript, not once
# for the instance.
TONES = ("neutral", "formal", "warm", "lively")

# What each tone asks the engine, in its own words. Written as a direction to a
# narrator rather than an adjective: the engine follows a brief better than a
# label, and an empty brief is how the neutral voice is obtained.
TONE_BRIEF = {
    "neutral": "",
    "formal": "Read in a calm, precise, professional tone, as in a lecture or a briefing.",
    "warm": "Read in a warm, kind, unhurried tone, as if explaining to someone you care about.",
    "lively": "Read with energy and enthusiasm, lively but still clear and articulate.",
}

# One synthesis at a time across the whole process, whatever the thread pool
# hands us. Requests queue; nothing is refused for that reason.
_synthesis = threading.Semaphore(max(1, settings.audio_concurrency))


class AudioUnavailable(RuntimeError):
    """The instance has no speech service, or the request cannot be served."""


def languages() -> list[str]:
    return [code.strip() for code in settings.audio_languages.split(",") if code.strip()]


def is_enabled() -> bool:
    return bool(settings.audio_enabled and settings.audio_service_url.strip())


def normalise_language(code: str | None, fallback: str = "en") -> str:
    value = (code or "").strip().lower().replace("_", "-")
    short = value.split("-")[0]
    if short in languages():
        return short
    return fallback if fallback in languages() else (languages() or ["en"])[0]


def voice_name(voice: str) -> str:
    return settings.audio_voice_male if voice == "male" else settings.audio_voice_female


def estimate(chars: int) -> dict[str, int]:
    """What a document of this size will cost, in CPU seconds and audio seconds."""
    audio_seconds = int(chars / CHARS_PER_AUDIO_SECOND)
    return {
        "audio_seconds": audio_seconds,
        "cpu_seconds": int(audio_seconds * CPU_SECONDS_PER_AUDIO_SECOND),
    }


# ---------------------------------------------------------------------------
# Markdown and HTML to something worth listening to
# ---------------------------------------------------------------------------

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`{1,3}([^`]*)`{1,3}")
_FOOTNOTE = re.compile(r"\[\^[^\]]*\]")
_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(.+?)\1")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE = re.compile(r"^\s{0,3}>\s?")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TAG = re.compile(r"<[^>]+>")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$")
_SPACES = re.compile(r"[ \t]+")


def markdown_to_speech(markdown: str) -> list[str]:
    """Turn Markdown into plain paragraphs.

    What is dropped is dropped because it cannot be read aloud: code, tables,
    image captions, raw URLs, footnote markers. What is kept is turned into
    sentences — headings get a full stop so the voice pauses.
    """
    text = (markdown or "").replace("\r\n", "\n")
    text = re.sub(r"```.*?```", "\n", text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", "\n", text, flags=re.S)
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            paragraphs.append(" ".join(buffer).strip())
            buffer.clear()

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if _TABLE_RULE.match(line):
            continue
        if line.lstrip().startswith("|"):
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            title = _clean(line[heading.end():])
            if title:
                paragraphs.append(title.rstrip(".") + ".")
            continue
        line = _QUOTE.sub("", line)
        # A list item is a sentence of its own: run together with the next one,
        # the voice never pauses and the listener hears one long riddle.
        if _LIST.match(line):
            flush()
            cleaned = _clean(_LIST.sub("", line))
            if cleaned:
                paragraphs.append(cleaned)
            continue
        cleaned = _clean(line)
        if cleaned:
            buffer.append(cleaned)
    flush()
    return [p for p in paragraphs if len(p) > 1]


def html_to_speech(markup: str) -> list[str]:
    text = html.unescape(_TAG.sub(" ", markup or ""))
    return [p.strip() for p in re.split(r"\n{2,}|\.\s{2,}", text) if p.strip()]


def _clean(line: str) -> str:
    line = _IMAGE.sub(" ", line)
    line = _LINK.sub(r"\1", line)
    line = _INLINE_CODE.sub(" ", line)
    line = _FOOTNOTE.sub(" ", line)
    line = _URL.sub(" ", line)
    line = _TAG.sub(" ", line)
    line = _EMPHASIS.sub(r"\2", line)
    line = line.replace("|", " ").replace("\\", " ")
    return _SPACES.sub(" ", line).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+")


def chunk(paragraphs: list[str], limit: int) -> list[str]:
    """Split paragraphs into pieces the synthesiser can chew in a minute.

    A sentence longer than the limit is cut on a comma, then on a space; nothing
    is ever dropped.
    """
    limit = max(120, limit)
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            while len(sentence) > limit:
                cut = max(sentence.rfind(",", 0, limit), sentence.rfind(" ", 0, limit))
                cut = cut if cut > limit // 2 else limit
                head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(head)
            if not current:
                current = sentence
            elif len(current) + 1 + len(sentence) <= limit:
                current = f"{current} {sentence}"
            else:
                pieces.append(current)
                current = sentence
    if current:
        pieces.append(current)
    return [p for p in pieces if p]


# ---------------------------------------------------------------------------
# Scripts, per kind of document
# ---------------------------------------------------------------------------


def _sections(db: OrmSession, owner_type: str, owner_id: int, language: str) -> list[dict]:
    if owner_type == "page":
        page = db.get(WikiPage, owner_id)
        if page is None:
            raise AudioUnavailable("Page not found.")
        paragraphs = [page.title.rstrip(".") + "."] + markdown_to_speech(page.content_md)
        return _group("page", paragraphs)

    if owner_type == "node":
        from .models import AdventureNode

        node = db.get(AdventureNode, owner_id)
        if node is None:
            raise AudioUnavailable("Scene not found.")
        paragraphs = _translated_html(node.text_html, node.text_translations, language)
        return _group("scene", paragraphs)

    raise AudioUnavailable(f"Only wiki pages and adventure scenes can be read aloud, not {owner_type}.")


def _translated_html(raw: str, translations: dict | None, language: str) -> list[str]:
    """Read the language of the document, not the one the interface happens to be in."""
    text = (translations or {}).get(language) if translations else None
    if text:
        return html_to_speech(text if "<" in text else text.replace("\n\n", "<p>"))
    return html_to_speech(raw)


def _group(prefix: str, paragraphs: list[str]) -> list[dict]:
    return [{"title": prefix, "paragraphs": paragraphs}] if paragraphs else []


def script_for(db: OrmSession, owner_type: str, owner_id: int, language: str) -> list[dict]:
    """The full script, chunked, with the hash that guards against stale audio."""
    sections = _sections(db, owner_type, owner_id, language)
    chunks: list[dict] = []
    for section in sections:
        for piece in chunk(section["paragraphs"], settings.audio_chunk_chars):
            chunks.append({"title": section["title"], "text": piece})
    if not chunks:
        raise AudioUnavailable("There is nothing to read in this document.")
    total = sum(len(c["text"]) for c in chunks)
    if total > settings.audio_max_chars:
        raise AudioUnavailable(
            f"This document is {total} characters long; the ceiling on this instance "
            f"is {settings.audio_max_chars}."
        )
    digest = hashlib.sha256(
        "\n".join(f"{c['title']}|{c['text']}" for c in chunks).encode("utf-8")
    ).hexdigest()
    return chunks, digest, total


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def _speak(text: str, language: str, voice: str, tone: str = "neutral") -> tuple[bytes, float]:
    url = settings.audio_service_url.rstrip("/") + "/v1/audio/speech"
    payload: dict[str, str] = {
        "model": settings.audio_model,
        "input": text,
        "voice": voice_name(voice),
        "language": language,
        "response_format": "mp3",
    }
    brief = TONE_BRIEF.get(tone, "")
    if brief:
        payload["instruct"] = brief
    try:
        with httpx.Client(timeout=settings.audio_timeout_seconds) as client:
            response = client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise AudioUnavailable(f"The speech service is unreachable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:300]
        raise AudioUnavailable(f"The speech service refused the text ({response.status_code}): {detail}")
    audio = response.content
    if not audio:
        raise AudioUnavailable("The speech service returned an empty file.")
    # An MP3 frame starts with 0xFF, or with an ID3 tag. This is not a decoder,
    # but it refuses an HTML error page saved as an mp3.
    if not (audio.startswith(b"ID3") or (len(audio) > 2 and audio[0] == 0xFF and audio[1] & 0xE0)):
        raise AudioUnavailable("The speech service did not return an MP3 file.")
    seconds = 0.0
    header = response.headers.get("X-Audio-Seconds")
    if header:
        try:
            seconds = float(header)
        except ValueError:
            seconds = 0.0
    return audio, seconds


def _store(audio: bytes) -> str:
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.mp3"
    (settings.media_dir / filename).write_bytes(audio)
    return f"/media/{filename}"


def _cache_key(text: str, language: str, voice: str, tone: str = "neutral") -> str:
    # The tone belongs to the key: without it, asking for the same paragraph in a
    # different voice would hand back the neutral recording, forever.
    body = f"{settings.audio_model}|{language}|{voice_name(voice)}|{tone}|{text}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _segment(db: OrmSession, text: str, language: str, voice: str, tone: str = "neutral") -> AudioSegment:
    key = _cache_key(text, language, voice, tone)
    existing = db.scalar(select(AudioSegment).where(AudioSegment.cache_key == key))
    if existing is not None:
        return existing
    audio, seconds = _speak(text, language, voice, tone)
    if not seconds:
        # Some engines do not report the duration; a 64 kbit/s mono MP3 carries
        # about 8 KiB per second, which is enough to size the player.
        seconds = len(audio) / 8192.0
    segment = AudioSegment(
        cache_key=key,
        language=language,
        voice=voice,
        tone=tone,
        model=settings.audio_model,
        path=_store(audio),
        seconds=round(seconds, 2),
        bytes=len(audio),
    )
    db.add(segment)
    db.commit()
    return segment


def run_audio_job(db: OrmSession, job: AiJob) -> dict:
    """Background entry point: one document, one voice, many cached segments."""
    payload = job.payload or {}
    owner_type = str(payload.get("owner_type") or "")
    owner_id = int(payload.get("owner_id") or 0)
    voice = str(payload.get("voice") or "female")
    if voice not in VOICES:
        raise AudioUnavailable("Unknown voice.")
    tone = str(payload.get("tone") or "neutral")
    if tone not in TONES:
        raise AudioUnavailable("Unknown tone.")
    if not is_enabled():
        raise AudioUnavailable("Audio is not enabled on this instance.")
    language = normalise_language(str(payload.get("language") or ""), str(payload.get("fallback") or "en"))

    chunks, digest, chars = script_for(db, owner_type, owner_id, language)
    total = len(chunks)

    with _synthesis:
        segments: list[dict] = []
        for index, piece in enumerate(chunks, start=1):
            _progress(db, job, int(100 * (index - 1) / total), f"{index}/{total}")
            segment = _segment(db, piece["text"], language, voice, tone)
            segments.append(
                {
                    "n": index,
                    "title": piece["title"],
                    "path": segment.path,
                    "seconds": segment.seconds,
                }
            )

    title = _document_title(db, owner_type, owner_id)
    previous = db.scalars(
        select(AudioRendition).where(
            AudioRendition.owner_type == owner_type,
            AudioRendition.owner_id == owner_id,
            AudioRendition.language == language,
            AudioRendition.voice == voice,
            AudioRendition.tone == tone,
        )
    ).all()
    for old in previous:
        db.delete(old)
    rendition = AudioRendition(
        owner_type=owner_type,
        owner_id=owner_id,
        language=language,
        voice=voice,
        tone=tone,
        model=settings.audio_model,
        title=title[:200],
        content_hash=digest,
        total_seconds=round(sum(s["seconds"] for s in segments), 1),
        segments=segments,
        created_by_id=job.user_id,
    )
    db.add(rendition)
    db.commit()
    return {
        "rendition_id": rendition.id,
        "segments": total,
        "seconds": rendition.total_seconds,
        "chars": chars,
    }


def _progress(db: OrmSession, job: AiJob, value: int, message: str) -> None:
    job.progress = max(0, min(value, 100))
    job.message = message[:300]
    db.commit()


def _document_title(db: OrmSession, owner_type: str, owner_id: int) -> str:
    if owner_type == "page":
        page = db.get(WikiPage, owner_id)
        if page is not None:
            wiki = db.get(Wiki, page.wiki_id)
            return f"{wiki.title} — {page.title}" if wiki else page.title
    if owner_type == "node":
        from .models import AdventureNode

        node = db.get(AdventureNode, owner_id)
        if node is not None:
            quiz = db.get(Quiz, node.quiz_id)
            return quiz.title if quiz else "Scene"
    return ""


def current_hash(db: OrmSession, owner_type: str, owner_id: int, language: str) -> str:
    """The hash of the text as it stands now, used to spot a stale transcript."""
    try:
        _, digest, _ = script_for(db, owner_type, owner_id, language)
    except AudioUnavailable:
        return ""
    return digest


def purge_renditions(
    db: OrmSession,
    owner_type: str,
    owner_id: int,
    *,
    rendition: AudioRendition | None = None,
    language: str | None = None,
    voice: str | None = None,
) -> int:
    """Delete renditions, then the cached pieces no other document still uses.

    Removing the row alone was not enough: the segment cache kept the file, so the
    next request returned the old recording in a fraction of a second and the
    interface said "ready" — the deletion had never happened. A segment is only
    removed when nothing else points at it, since two pages may share a sentence.
    """
    query = select(AudioRendition).where(
        AudioRendition.owner_type == owner_type, AudioRendition.owner_id == owner_id
    )
    if rendition is not None:
        query = query.where(AudioRendition.id == rendition.id)
    if language:
        query = query.where(AudioRendition.language == language)
    if voice:
        query = query.where(AudioRendition.voice == voice)
    rows = list(db.scalars(query).all())
    if not rows:
        return 0

    paths: set[str] = set()
    for row in rows:
        for segment in row.segments or []:
            path = str(segment.get("path") or "")
            if path:
                paths.add(path)
        db.delete(row)
    db.commit()

    if not paths:
        return 0

    # What the rest of the database still references, read once.
    still_used: set[str] = set()
    for other in db.scalars(select(AudioRendition)).all():
        for segment in other.segments or []:
            path = str(segment.get("path") or "")
            if path:
                still_used.add(path)

    removed = 0
    for segment in db.scalars(select(AudioSegment).where(AudioSegment.path.in_(paths))).all():
        if segment.path in still_used:
            continue
        media = _media_file(segment.path)
        db.delete(segment)
        removed += 1
        if media is not None:
            media.unlink(missing_ok=True)
    db.commit()
    return removed


def _media_file(path: str):
    """The file behind a ``/media/...`` path, if it is inside the media directory."""
    name = path.rsplit("/", 1)[-1]
    if not name or "/" in name or name.startswith("."):
        return None
    candidate = settings.media_dir / name
    try:
        candidate.resolve().relative_to(settings.media_dir.resolve())
    except (ValueError, OSError):
        return None
    return candidate
