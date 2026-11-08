# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Crawlable metadata for the single page application.

The front end is a SPA: a crawler that does not execute JavaScript only sees an
empty shell. These helpers do not try to render the app — they fill the shell
with what a search engine or a chat preview needs: title, description, canonical
URL, Open Graph and Twitter tags, and a small JSON-LD payload.

Everything here is defensive. A missing, private or moderated document falls
back to the generic tags, because a broken title must never turn a page into an
error for a human reader.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select

from .db import SessionLocal
from .models import Quiz, Wiki, WikiPage

router = APIRouter()

QUIZ_PATH = re.compile(r"^/quizzes/(?P<id>\d+)(?:/(?P<slug>[^/]*))?/?$")
WIKI_PAGE_PATH = re.compile(r"^/wiki/(?P<id>\d+)/p/(?P<slug>[^/]+)/?$")
WIKI_PATH = re.compile(r"^/wiki/(?P<id>\d+)(?:/(?P<slug>[^/]*))?/?$")

DEFAULT_TITLE = "OpenLearn — learn together, teach freely"
DEFAULT_DESCRIPTION = (
    "A free, self-hosted platform to build quizzes, wikis, revision sheets and "
    "story adventures, in eight languages, with or without an account."
)


def base_url(request: Request) -> str:
    """The public origin, as the reverse proxy reports it."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _clip(value: str | None, length: int) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def _head(
    *,
    origin: str,
    path: str,
    title: str,
    description: str,
    kind: str = "website",
    image: str | None = None,
    json_ld: dict | None = None,
) -> str:
    url = f"{origin}{path}"
    tags = [
        f'<meta name="description" content="{escape(description, quote=True)}" />',
        f'<link rel="canonical" href="{escape(url, quote=True)}" />',
        '<meta property="og:site_name" content="OpenLearn" />',
        f'<meta property="og:type" content="{kind}" />',
        f'<meta property="og:title" content="{escape(title, quote=True)}" />',
        f'<meta property="og:description" content="{escape(description, quote=True)}" />',
        f'<meta property="og:url" content="{escape(url, quote=True)}" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{escape(title, quote=True)}" />',
        f'<meta name="twitter:description" content="{escape(description, quote=True)}" />',
    ]
    if image:
        absolute = image if image.startswith("http") else f"{origin}{image}"
        tags += [
            f'<meta property="og:image" content="{escape(absolute, quote=True)}" />',
            f'<meta name="twitter:image" content="{escape(absolute, quote=True)}" />',
        ]
    if json_ld:
        payload = json.dumps(json_ld, ensure_ascii=False, separators=(",", ":"))
        # A JSON-LD block is data, not script: no interpolation of user text.
        tags.append(f'<script type="application/ld+json">{payload}</script>')
    return "\n    ".join(tags)


def _quiz_meta(db, quiz_id: int, origin: str, path_hint: str) -> tuple[str, str, str, str | None, dict]:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.status != "public":
        return DEFAULT_TITLE, DEFAULT_DESCRIPTION, path_hint, None, {}
    slug = _slug(quiz.title)
    canonical = f"/quizzes/{quiz.id}/{slug}"
    title = f"{quiz.title} — a quiz on OpenLearn"
    description = _clip(quiz.description, 200) or (
        f"A free quiz on OpenLearn: {quiz.title}. Play it on your own, or host it live for a group."
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Quiz",
        "name": quiz.title,
        "description": description,
        "url": f"{origin}{canonical}",
        "inLanguage": quiz.default_language or "en",
        "isAccessibleForFree": True,
    }
    return title, description, canonical, None, json_ld


def _wiki_meta(
    db, wiki_id: int, page_slug: str | None, origin: str
) -> tuple[str, str, str, str | None, dict]:
    wiki = db.get(Wiki, wiki_id)
    if wiki is None or wiki.status != "public":
        return DEFAULT_TITLE, DEFAULT_DESCRIPTION, f"/wiki/{wiki_id}", None, {}
    wiki_slug = wiki.slug or _slug(wiki.title)
    if page_slug:
        page = db.scalar(
            select(WikiPage).where(WikiPage.wiki_id == wiki.id, WikiPage.slug == page_slug)
        )
        if page is not None:
            canonical = f"/wiki/{wiki.id}/p/{page.slug}"
            description = _clip(page.content_md, 200) or _clip(wiki.description, 200)
            title = f"{page.title} — {wiki.title}"
            json_ld = {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": page.title,
                "description": description,
                "url": f"{origin}{canonical}",
                "inLanguage": wiki.default_language or "en",
                "isPartOf": {"@type": "CreativeWork", "name": wiki.title},
                "isAccessibleForFree": True,
                **(_date(page.updated_at) and {"dateModified": _date(page.updated_at)} or {}),
            }
            image = wiki.cover_image
            return title, description or DEFAULT_DESCRIPTION, canonical, image, json_ld
    canonical = f"/wiki/{wiki.id}/{wiki_slug}"
    description = _clip(wiki.description, 200) or (
        f"{wiki.title}: a shared knowledge base of pages, readable and editable together."
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": wiki.title,
        "description": description,
        "url": f"{origin}{canonical}",
        "inLanguage": wiki.default_language or "en",
        "isAccessibleForFree": True,
    }
    return f"{wiki.title} — a wiki on OpenLearn", description, canonical, wiki.cover_image, json_ld


def _date(value) -> str | None:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.date().isoformat()
    return None


def _slug(title: str) -> str:
    from .wiki import slugify

    return slugify(title or "openlearn", fallback="openlearn")


def render_shell(request: Request, html: str, path: str) -> str:
    """Return `html` with the head tags for `path` spliced in."""
    title, description, canonical, image, json_ld = DEFAULT_TITLE, DEFAULT_DESCRIPTION, path, None, {}
    origin = base_url(request)
    match_quiz = QUIZ_PATH.match(path)
    match_page = WIKI_PAGE_PATH.match(path)
    match_wiki = WIKI_PATH.match(path) if not match_page else None
    try:
        if match_quiz:
            with SessionLocal() as db:
                title, description, canonical, image, json_ld = _quiz_meta(
                    db, int(match_quiz.group("id")), origin, path
                )
        elif match_page:
            with SessionLocal() as db:
                title, description, canonical, image, json_ld = _wiki_meta(
                    db, int(match_page.group("id")), match_page.group("slug"), origin
                )
        elif match_wiki:
            with SessionLocal() as db:
                title, description, canonical, image, json_ld = _wiki_meta(
                    db, int(match_wiki.group("id")), None, origin
                )
    except Exception:  # a database hiccup must not break the page
        title, description, canonical, image, json_ld = DEFAULT_TITLE, DEFAULT_DESCRIPTION, path, None, {}

    head = _head(
        origin=origin,
        path=canonical,
        title=title,
        description=description,
        kind="article" if (match_page or match_quiz) else "website",
        image=image,
        json_ld=json_ld or None,
    )
    # Replace the static title so the tab and the preview agree.
    html = re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html, count=1, flags=re.S)
    return html.replace("</head>", f"    {head}\n  </head>", 1)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request) -> Response:
    """Every public document, so search engines can find the catalogue."""
    origin = base_url(request)
    urls: list[tuple[str, str | None]] = [
        ("/", None),
        ("/quizzes", None),
        ("/wiki", None),
        ("/legal", None),
    ]
    try:
        with SessionLocal() as db:
            for quiz in db.scalars(select(Quiz).where(Quiz.status == "public").limit(5000)):
                urls.append((f"/quizzes/{quiz.id}/{_slug(quiz.title)}", _date(quiz.updated_at)))
            for wiki in db.scalars(select(Wiki).where(Wiki.status == "public").limit(2000)):
                wiki_slug = wiki.slug or _slug(wiki.title)
                urls.append((f"/wiki/{wiki.id}/{wiki_slug}", _date(wiki.updated_at)))
                for page in db.scalars(
                    select(WikiPage).where(WikiPage.wiki_id == wiki.id).limit(2000)
                ):
                    urls.append((f"/wiki/{wiki.id}/p/{page.slug}", _date(page.updated_at)))
    except Exception:  # an empty sitemap beats a 500
        pass
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, lastmod in urls:
        entry = f"  <url><loc>{escape(origin + path)}</loc>"
        if lastmod:
            entry += f"<lastmod>{lastmod}</lastmod>"
        body.append(entry + "</url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request) -> PlainTextResponse:
    origin = base_url(request)
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /$",
            "Allow: /quizzes",
            "Allow: /wiki",
            "Allow: /docs",
            # Nothing personal is served without a session, but a crawler has no
            # business in the account or editing surfaces.
            "Disallow: /admin",
            "Disallow: /settings",
            "Disallow: /api/",
            "Disallow: /media/",
            "",
            f"Sitemap: {origin}/sitemap.xml",
            "",
        ]
    )
    return PlainTextResponse(body)
