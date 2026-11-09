# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""FastAPI application factory: routing, static assets, security headers."""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import collab
from . import mcp as mcp_module
from .config import BASE_DIR, public_base_url_problem, settings
from .db import SessionLocal, init_db
from .routers import (
    account_recovery,
    admin,
    admin_settings,
    adventure,
    auth,
    cards,
    evaluation,
    generate,
    instance,
    legal,
    quizzes,
    sessions,
    sso_auth,
    uploads,
    users,
    wiki,
    wiki_ai,
    wiki_collab,
)
from .search import ensure_index, ensure_wiki_index
from .seo import render_shell
from .seo import router as seo_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("openlearn")


FRONTEND_DIR = BASE_DIR / "frontend"
MAX_JSON_BODY = 2 * 1024 * 1024  # quiz documents stay well under 2 MB


def warn_about_unreachable_public_base() -> None:
    """Say at startup whether outgoing links point somewhere a reader can open."""
    problem = public_base_url_problem(settings.public_base_url)
    if problem:
        logger.warning("OL_PUBLIC_BASE_URL: %s", problem)
    elif settings.public_base_url:
        logger.info("Public links will use %s", settings.public_base_url.rstrip("/"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenLearn API",
        version="2.0.0",
        description=(
            "Self-hosted learning platform: questionnaires (quiz, swipe, poll, "
            "adventure) and a markdown wiki. See API.md for the full reference."
        ),
        # The generated Swagger page needs inline scripts and a CDN, both blocked
        # by our CSP: it came out blank, which read as a broken app. The SPA
        # renders the same OpenAPI document at /docs instead.
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Reject oversized JSON bodies early (OWASP A04 - resource exhaustion).
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            is_upload = request.url.path.startswith("/api/v1/uploads")
            if length and length.isdigit() and int(length) > (settings.max_upload_bytes + 4096 if is_upload else MAX_JSON_BODY):
                return JSONResponse(status_code=status.HTTP_413_CONTENT_TOO_LARGE, content={"detail": "Payload too large."})

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' ws: wss:; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        if settings.cookie_secure or forwarded_proto == "https":
            csp += "; upgrade-insecure-requests"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = csp
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def backfill_versions(db) -> None:
        """Existing public quizzes predate versioning: freeze their content."""
        from .models import Quiz
        from .versions import freeze

        for quiz in db.scalars(select(Quiz).where(Quiz.status == "public")).all():
            if quiz.published_version_number:
                continue
            version = freeze(
                db,
                quiz,
                user=None,
                publish=True,
                auto_publish=True,
                note="Imported before versioning",
            )
            db.add(quiz)
            db.add(version)
            logger.info("Version 1 created for quiz %s", quiz.id)
        db.commit()

    def refresh_live_index(db) -> None:
        """Point the search index at the published version of every live quiz.

        The FTS triggers index the working copy, which is right for an author
        looking for their own drafts but wrong for the public catalogue.
        """
        from .models import Quiz
        from .search import refresh_quiz

        for quiz in db.scalars(select(Quiz).where(Quiz.status == "public")).all():
            refresh_quiz(db, quiz)

    def _startup() -> None:
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        # Live editing rooms broadcast from the serving loop, including from
        # synchronous routes running in the threadpool.
        collab.bind_loop()
        init_db()
        with SessionLocal() as db:
            ensure_index(db)
            ensure_wiki_index(db)
            backfill_versions(db)
            refresh_live_index(db)
            from .wiki_ai import stale_jobs

            interrupted = stale_jobs(db)
            if interrupted:
                logger.info("%s interrupted AI job(s) marked as failed", interrupted)
        from .seed import ensure_admin, seed_demo_content

        ensure_admin()
        if settings.demo_mode:
            # Demo instances publish a showcase catalogue in several languages.
            from .demo.seed import seed_showcase

            seed_showcase()
        elif settings.seed_demo_data:
            seed_demo_content()
        # An empty key is legal (Ollama needs none) but a provider answered 401
        # for a whole afternoon because nobody was told. Say it once, loudly.
        if settings.ai_enabled and settings.ai_base_url and not settings.ai_api_key:
            logger.warning(
                "AI is enabled but OL_AI_API_KEY is empty: model calls will be rejected "
                "unless %s accepts anonymous requests",
                settings.ai_base_url,
            )
        # Every reset and verification mail quotes this address; a wrong one is
        # only discovered by the person who clicks the dead link.
        warn_about_unreachable_public_base()
        logger.info(
            "OpenLearn ready (database=%s, demo=%s)", settings.database_url, settings.demo_mode
        )

    @app.get("/api/v1/health", tags=["system"])
    def health() -> dict[str, object]:
        from . import runtime

        return {
            "status": "ok",
            "app": settings.app_name,
            "version": app.version,
            "environment": settings.environment,
            "demo": bool(settings.demo_mode),
            "ai": bool(runtime.ai_config().enabled),
        }

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(quizzes.router)
    app.include_router(uploads.router)
    app.include_router(sessions.router)
    app.include_router(adventure.router)
    app.include_router(admin.router)
    app.include_router(generate.router)
    app.include_router(wiki.router)
    app.include_router(wiki_ai.router)
    app.include_router(wiki_collab.router)
    app.include_router(evaluation.router)
    app.include_router(cards.router)
    app.include_router(account_recovery.router)
    app.include_router(sso_auth.router)
    app.include_router(admin_settings.router)
    app.include_router(instance.router)
    app.include_router(legal.router)
    app.include_router(mcp_module.router)

    settings.media_dir.mkdir(parents=True, exist_ok=True)
    # Uploads are re-encoded to WEBP; slim base images ship no /etc/mime.types,
    # so declare the type explicitly or StaticFiles serves them as text/plain.
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("image/jpeg", ".jpg")
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    @app.get("/docs/mcp.md", include_in_schema=False)
    def mcp_documentation() -> Response:
        """The MCP guide, served as Markdown for the in-app documentation page.

        It is the same file the repository ships, so the page cannot drift from
        the documentation a reader finds on GitHub.
        """
        # The checkout keeps docs/ beside backend/, the image keeps it beside
        # app/: look in both, then next to the configured base directory.
        here = Path(__file__).resolve()
        candidates = [
            here.parents[index] / "docs" / "MCP.md" for index in (2, 3) if index < len(here.parents)
        ]
        candidates.append(Path(BASE_DIR) / "docs" / "MCP.md")
        for path in candidates:
            if path.is_file():
                return Response(
                    content=path.read_text(encoding="utf-8"),
                    media_type="text/markdown; charset=utf-8",
                )
        raise HTTPException(status_code=404, detail="Documentation unavailable.")

    @app.get("/api/docs", include_in_schema=False)
    @app.get("/api/redoc", include_in_schema=False)
    def legacy_docs() -> RedirectResponse:
        """The FastAPI Swagger page cannot run under our CSP: hand over to /docs."""
        return RedirectResponse(url="/docs", status_code=307)

    app.include_router(seo_router)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        """Serve the single page application and its static assets."""
        if full_path.startswith(("api/", "media/")):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = _safe_frontend_path(full_path)
        # An unreadable path is not a file either. Without this the whole shell
        # answers 500 because one directory denies stat to the application user.
        try:
            if candidate is not None and candidate.is_file():
                return FileResponse(candidate)
        except OSError:
            pass
        index = FRONTEND_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built.")
        # The app is a SPA, so the shell is what a crawler sees. Give it the
        # title, description and canonical URL of the document being asked for.
        html = render_shell(request, index.read_text(encoding="utf-8"), "/" + full_path)
        return Response(
            html,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    # `on_event` is deprecated and the same body belongs in a lifespan hook. The
    # handler is registered here because everything it touches is defined above.
    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        _startup()
        yield

    app.router.lifespan_context = _lifespan
    return app


def _safe_frontend_path(full_path: str) -> Path | None:
    """Resolve a request path inside the frontend directory (no traversal)."""
    if not full_path:
        return None
    try:
        base = FRONTEND_DIR.resolve()
        candidate = (base / full_path).resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(base):
        return None
    return candidate


app = create_app()
