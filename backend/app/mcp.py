# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Model Context Protocol endpoint: let an external agent read OpenLearn.

The server speaks JSON-RPC 2.0 over HTTP (the "streamable HTTP" transport of
MCP, without the optional SSE stream). It exposes the public knowledge of the
instance — wikis, pages, quizzes — as tools, so an assistant can answer from a
course rather than from its training data.

Only public content is reachable, plus the caller's own drafts when the request
is authenticated. No tool writes: an agent that could edit a wiki through this
endpoint would need a much stronger consent model than a bearer token.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from . import runtime, search
from .config import settings
from .db import get_db
from .deps import client_ip, resolve_user
from .models import Question, Quiz, User, Wiki, WikiPage
from .security import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "3.0.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "openlearn_instance_info",
        "description": "Describe this OpenLearn instance: name, languages, available content types.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "openlearn_list_wikis",
        "description": "List the public wikis of the instance, newest first. Optionally filter by text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free text filter on the title."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "openlearn_get_wiki",
        "description": "Read one wiki: description, language, and the list of its pages.",
        "inputSchema": {
            "type": "object",
            "properties": {"wiki_id": {"type": "integer"}},
            "required": ["wiki_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "openlearn_search_pages",
        "description": "Full-text search inside the public wikis. Returns page titles with a snippet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for."},
                "wiki_id": {"type": "integer", "description": "Restrict the search to one wiki."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "openlearn_get_page",
        "description": "Read a wiki page as markdown. Identify it by page_id, or by wiki_id plus slug.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "integer"},
                "wiki_id": {"type": "integer"},
                "slug": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "openlearn_list_quizzes",
        "description": "List the published questionnaires (quiz, swipe cards, polls, adventures).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {"type": "string", "enum": ["qcm", "swipe", "adventure", "poll"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "openlearn_get_quiz",
        "description": "Read a questionnaire: description, question count and public join link.",
        "inputSchema": {
            "type": "object",
            "properties": {"quiz_id": {"type": "integer"}},
            "required": ["quiz_id"],
            "additionalProperties": False,
        },
    },
]


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def _snippet(markdown: str, query: str, *, size: int = 240) -> str:
    """A short plain-text excerpt around the first matching word."""
    plain = " ".join((markdown or "").split())
    needle = (query.split() or [""])[0].lower()
    position = plain.lower().find(needle) if needle else -1
    start = max(0, position - 60) if position > 0 else 0
    excerpt = plain[start : start + size]
    return ("…" if start else "") + excerpt + ("…" if start + size < len(plain) else "")


def _text(payload: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
        "structuredContent": payload,
        "isError": False,
    }


def _readable_wikis(db: OrmSession, user: User | None) -> list[Any]:
    clauses = [Wiki.status == "public"]
    if user is not None:
        clauses.append(Wiki.owner_id == user.id)
    return list(clauses)


def _tool_list_wikis(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 50))
    statement = select(Wiki).where(or_(*_readable_wikis(db, user)))
    query = (args.get("query") or "").strip()
    if query:
        statement = statement.where(Wiki.title.ilike(f"%{query}%"))
    rows = db.scalars(statement.order_by(Wiki.updated_at.desc()).limit(limit)).all()
    return _text(
        {
            "wikis": [
                {
                    "id": wiki.id,
                    "title": wiki.title,
                    "url": f"{base}/wiki/{wiki.id}",
                    "description": wiki.description,
                    "language": wiki.default_language,
                }
                for wiki in rows
            ]
        }
    )


def _tool_get_wiki(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    wiki = db.get(Wiki, int(args.get("wiki_id") or 0))
    if wiki is None or (wiki.status != "public" and (user is None or wiki.owner_id != user.id)):
        raise RpcError(-32004, "Wiki not found.")
    pages = db.scalars(select(WikiPage).where(WikiPage.wiki_id == wiki.id).order_by(WikiPage.position)).all()
    return _text(
        {
            "id": wiki.id,
            "title": wiki.title,
            "description": wiki.description,
            "language": wiki.default_language,
            "url": f"{base}/wiki/{wiki.id}",
            "pages": [
                {
                    "id": page.id,
                    "title": page.title,
                    "slug": page.slug,
                    "url": f"{base}/wiki/{wiki.id}/p/{page.slug}",
                    "tags": page.tags or [],
                }
                for page in pages
            ],
        }
    )


def _tool_search_pages(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        raise RpcError(-32602, "query is required")
    limit = max(1, min(int(args.get("limit") or 10), 30))
    wiki_filter = int(args["wiki_id"]) if args.get("wiki_id") else None
    hits = search.search_wiki_pages(
        db, query, wiki_ids=[wiki_filter] if wiki_filter else None, limit=limit * 3
    )
    page_ids: list[int]
    if hits is None:
        # No FTS5 (PostgreSQL/MySQL, or an unfinished index): fall back to a
        # LIKE scan, which is slow but never silently empty.
        statement = select(WikiPage.id).where(
            or_(WikiPage.title.ilike(f"%{query}%"), WikiPage.content_md.ilike(f"%{query}%"))
        )
        if wiki_filter:
            statement = statement.where(WikiPage.wiki_id == wiki_filter)
        page_ids = list(db.scalars(statement.limit(limit * 3)).all())
    else:
        page_ids = [page_id for page_id, _score in hits]
    results = []
    for page_id in page_ids:
        page = db.get(WikiPage, page_id)
        if page is None:
            continue
        wiki = db.get(Wiki, page.wiki_id)
        if wiki is None or wiki.status != "public":
            if user is None or wiki is None or wiki.owner_id != user.id:
                continue
        if wiki_filter and wiki.id != int(wiki_filter):
            continue
        results.append(
            {
                "page_id": page.id,
                "wiki_id": wiki.id,
                "title": page.title,
                "snippet": _snippet(page.content_md, query),
                "url": f"{base}/wiki/{wiki.id}/p/{page.slug}",
            }
        )
        if len(results) >= limit:
            break
    return _text({"query": query, "results": results})


def _tool_get_page(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    page = None
    if args.get("page_id"):
        page = db.get(WikiPage, int(args["page_id"]))
    elif args.get("wiki_id") and args.get("slug"):
        page = db.scalar(
            select(WikiPage).where(
                WikiPage.wiki_id == int(args["wiki_id"]), WikiPage.slug == str(args["slug"])
            )
        )
    if page is None:
        raise RpcError(-32004, "Page not found.")
    wiki = db.get(Wiki, page.wiki_id)
    if wiki is None or (wiki.status != "public" and (user is None or wiki.owner_id != user.id)):
        raise RpcError(-32004, "Page not found.")
    return _text(
        {
            "page_id": page.id,
            "wiki_id": wiki.id,
            "wiki_title": wiki.title,
            "title": page.title,
            "slug": page.slug,
            "tags": page.tags or [],
            "markdown": page.content_md,
            "url": f"{base}/wiki/{wiki.id}/p/{page.slug}",
        }
    )


def _tool_list_quizzes(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 50))
    statement = select(Quiz).where(Quiz.status == "public")
    query = (args.get("query") or "").strip()
    if query:
        statement = statement.where(Quiz.title.ilike(f"%{query}%"))
    if args.get("mode"):
        statement = statement.where(Quiz.mode == str(args["mode"]))
    rows = db.scalars(statement.order_by(
            Quiz.published_at.is_(None), Quiz.published_at.desc(), Quiz.id.desc()
        ).limit(limit)).all()
    return _text(
        {
            "quizzes": [
                {
                    "id": quiz.id,
                    "title": quiz.title,
                    "mode": quiz.mode,
                    "language": quiz.default_language,
                    "url": f"{base}/quizzes/{quiz.id}",
                }
                for quiz in rows
            ]
        }
    )


def _tool_get_quiz(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    quiz = db.get(Quiz, int(args.get("quiz_id") or 0))
    if quiz is None or (quiz.status != "public" and (user is None or quiz.owner_id != user.id)):
        raise RpcError(-32004, "Quiz not found.")
    count = len(quiz.questions) if hasattr(quiz, "questions") else 0
    return _text(
        {
            "id": quiz.id,
            "title": quiz.title,
            "description": quiz.description,
            "mode": quiz.mode,
            "language": quiz.default_language,
            "languages": quiz.languages or [],
            "question_count": count,
            "url": f"{base}/quizzes/{quiz.id}",
        }
    )


def _tool_instance_info(db: OrmSession, user: User | None, args: dict, base: str) -> dict[str, Any]:
    return _text(
        {
            "name": runtime.instance_name(db),
            "url": base,
            "demo_mode": settings.demo_mode,
            "languages": ["en", "fr", "it", "es", "de", "ru", "zh", "ja"],
            "content": ["wiki", "quiz", "swipe", "poll", "adventure", "revision cards"],
        }
    )


HANDLERS = {
    "openlearn_instance_info": _tool_instance_info,
    "openlearn_list_wikis": _tool_list_wikis,
    "openlearn_get_wiki": _tool_get_wiki,
    "openlearn_search_pages": _tool_search_pages,
    "openlearn_get_page": _tool_get_page,
    "openlearn_list_quizzes": _tool_list_quizzes,
    "openlearn_get_quiz": _tool_get_quiz,
}


def _error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=200,
    )


@router.get("/mcp", include_in_schema=False)
def mcp_descriptor(request: Request) -> Response:
    """Human- and probe-friendly description of the endpoint."""
    if not settings.mcp_enabled:
        return JSONResponse({"error": "MCP is disabled on this instance."}, status_code=404)
    return JSONResponse(
        {
            "protocol": "mcp",
            "protocolVersion": PROTOCOL_VERSION,
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "auth": "Authorization: Bearer <api key> or X-API-Key" if settings.mcp_require_auth else "none",
            "tools": [tool["name"] for tool in TOOLS],
        }
    )


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(request: Request, db: OrmSession = Depends(get_db)) -> Response:
    if not settings.mcp_enabled:
        return JSONResponse({"error": "MCP is disabled on this instance."}, status_code=404)

    allowed, retry_after = rate_limiter.check(
        f"mcp:{client_ip(request)}", settings.mcp_rate_limit, settings.mcp_rate_window_seconds
    )
    if not allowed:
        return JSONResponse(
            {"error": "Too many requests."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    user = resolve_user(request, db)
    if settings.mcp_require_auth and user is None:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Authentication required."}},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        body = await request.json()
    except ValueError:
        return _error(None, -32700, "Parse error")
    if isinstance(body, list):
        # Batch requests are optional in the spec; supporting them costs a loop.
        answers = [_handle_one(item, db, user, request) for item in body]
        return JSONResponse([a for a in answers if a is not None])

    answer = _handle_one(body, db, user, request)
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(answer)


def _handle_one(body: Any, db: OrmSession, user: User | None, request: Request) -> dict[str, Any] | None:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params") or {}

    # Notifications carry no id and expect no answer.
    if request_id is None and isinstance(method, str) and method.startswith("notifications/"):
        return None

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "openlearn", "version": SERVER_VERSION},
                    "instructions": (
                        "OpenLearn exposes shared knowledge: wikis of markdown pages and "
                        "self-training questionnaires. Search before reading, and cite the "
                        "page URL you used."
                    ),
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            handler = HANDLERS.get(name)
            if handler is None:
                raise RpcError(-32601, f"Unknown tool: {name}")
            if not isinstance(arguments, dict):
                raise RpcError(-32602, "arguments must be an object")
            return {"jsonrpc": "2.0", "id": request_id, "result": handler(db, user, arguments, _base(request))}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
        raise RpcError(-32601, f"Method not found: {method}")
    except RpcError as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": exc.message}}
    except Exception:  # pragma: no cover - defensive: an MCP error must stay JSON
        logger.exception("MCP tool failed")
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal error"}}
