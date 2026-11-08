# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Wiki API: wikis, pages, versions, diffs, proposals, members and exports.

Access control (OWASP A01) is central here: a wiki is a shared document tree with
four kinds of readers, so every route resolves the caller's role *before* it
touches a row.

    owner        the creator, or an administrator moderating the wiki
    maintainer   invited by the owner, writes pages directly
    contributor  invited by the owner, submits proposals an owner must accept
    reader       anybody who may read the wiki, including anonymous visitors on
                 a public wiki; a signed-in reader may still propose an edit

A save by an owner or a maintainer writes the page and freezes a version. A save
by a contributor (or by a reader) is stored as a proposal instead: the live page
never changes until somebody with write rights accepts it.
"""

from __future__ import annotations

import json
import logging
import re
from html import escape

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session as OrmSession

from .. import collab, pdf_export, search, wiki_ai
from ..config import settings
from ..db import get_db
from ..deps import enforce_ai_interval, get_optional_user, require_user
from ..models import (
    Option,
    Question,
    Quiz,
    User,
    Wiki,
    WikiLink,
    WikiMember,
    WikiPage,
    WikiPageDraft,
    WikiPageVersion,
    WikiProposal,
    WikiQuizLink,
    WikiReference,
    WikiTemplate,
    utcnow,
)
from ..schemas import (
    WikiCanvasIn,
    WikiIn,
    WikiMemberIn,
    WikiPageIn,
    WikiProposalIn,
    WikiPublishIn,
    WikiQuizGenerateIn,
    WikiQuizLinkIn,
    WikiReferenceIn,
    WikiReviewIn,
    WikiTemplateIn,
    WikiTreeIn,
)
from ..wiki import (
    build_zip,
    diff_stats,
    excerpt,
    extract_external_links,
    host_of,
    outline,
    page_breadcrumb,
    rebuild_links,
    reflow_markdown,
    render_markdown,
    rewrite_links_for_export,
    side_by_side_diff,
    slugify,
    unified_diff,
    unique_slug,
)
from ..wiki_import import ImportedPage, parse_markdown_file, read_archive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])

MAX_WIKI_PAGES = 500
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]{1,180})(?:\|[^\]]{1,180})?\]\]")
_WIKI_HREF_RE = re.compile(r"\]\(/wiki/p/([a-z0-9\-]+)\)")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def _member_role(db: OrmSession, wiki: Wiki, user: User | None) -> str | None:
    if user is None:
        return None
    if user.id == wiki.owner_id:
        return "owner"
    if user.is_staff:
        # Administrators write everywhere, not just moderate: a moderator who
        # cannot fix a typo has to file a proposal against himself.
        return "maintainer"
    row = db.scalar(
        select(WikiMember).where(WikiMember.wiki_id == wiki.id, WikiMember.user_id == user.id)
    )
    return row.role if row else None


def _readable(wiki: Wiki, role: str | None) -> bool:
    if wiki.status == "public":
        return True
    return role in {"owner", "maintainer", "contributor", "moderator"}


def _writable(role: str | None) -> bool:
    return role in {"owner", "maintainer"}


def _require_read(db: OrmSession, wiki: Wiki, user: User | None) -> str | None:
    role = _member_role(db, wiki, user)
    if not _readable(wiki, role):
        # A private wiki must be indistinguishable from a missing one.
        raise HTTPException(status_code=404, detail="Wiki not found.")
    return role


def _require_write(db: OrmSession, wiki: Wiki, user: User) -> str:
    role = _member_role(db, wiki, user)
    if role in {"owner", "maintainer", "moderator"}:
        return role
    raise HTTPException(status_code=403, detail="You cannot edit this wiki.")


def _get_wiki(db: OrmSession, wiki_id: int) -> Wiki:
    wiki = db.get(Wiki, wiki_id)
    if wiki is None:
        raise HTTPException(status_code=404, detail="Wiki not found.")
    return wiki


def _get_page(db: OrmSession, page_id: int) -> WikiPage:
    page = db.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    return page


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
def _page_slug_map(db: OrmSession, wiki_id: int) -> dict[str, str]:
    """Slug *and* title of every page, lower-cased, to resolve ``[[links]]``."""
    mapping: dict[str, str] = {}
    for page in db.scalars(select(WikiPage).where(WikiPage.wiki_id == wiki_id)).all():
        mapping[page.slug.lower()] = page.slug
        mapping[page.title.lower()] = page.slug
    return mapping


def _serialise_wiki(
    db: OrmSession, wiki: Wiki, role: str | None, user: User | None = None
) -> dict:
    page_count = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    owner = db.get(User, wiki.owner_id)
    members = db.scalars(select(WikiMember).where(WikiMember.wiki_id == wiki.id)).all()
    return {
        "id": wiki.id,
        "title": wiki.title,
        "slug": wiki.slug,
        "description": wiki.description,
        "status": wiki.status,
        "is_public": wiki.is_public,
        "cover_image": wiki.cover_image,
        "moderation_note": wiki.moderation_note,
        "default_language": wiki.default_language,
        "page_count": page_count,
        "owner": {"id": owner.id, "display_name": owner.display_name} if owner else None,
        "role": role,
        "can_write": _writable(role),
        # Only the owner (or an administrator) may erase the whole wiki.
        "can_delete": bool(
            user is not None and (wiki.owner_id == user.id or getattr(user, "is_staff", False))
        ),
        "created_at": wiki.created_at,
        "updated_at": wiki.updated_at,
        "published_at": wiki.published_at,
        "members": [{"user_id": m.user_id, "role": m.role} for m in members],
    }


def _serialise_page(
    page: WikiPage, *, with_html: bool = False, pages: dict[str, str] | None = None
) -> dict:
    payload = {
        "id": page.id,
        "wiki_id": page.wiki_id,
        "slug": page.slug,
        "title": page.title,
        "content_md": page.content_md,
        "tags": page.tags or [],
        "position": page.position,
        "parent_id": page.parent_id,
        "version": page.current_version_number,
        "excerpt": excerpt(page.content_md),
        "updated_at": page.updated_at,
        "outline": outline(page.content_md),
    }
    if with_html:
        payload["html"] = render_markdown(page.content_md, pages=pages or {})
    return payload


def _backlinks(db: OrmSession, page: WikiPage) -> list[dict]:
    rows = db.execute(
        select(WikiPage.id, WikiPage.title, WikiPage.slug)
        .join(WikiLink, WikiLink.from_page_id == WikiPage.id)
        .where(WikiLink.to_page_id == page.id)
        .distinct()
    ).all()
    return [{"id": row[0], "title": row[1], "slug": row[2]} for row in rows]


def _rebuild_links(db: OrmSession, page: WikiPage) -> None:
    """Kept as a thin alias: link rebuilding also runs from live autosaves."""
    rebuild_links(db, page)


def _drop_draft(db: OrmSession, page_id: int) -> None:
    """Forget the working copy of a page (after a save or a restore)."""
    draft = db.scalar(select(WikiPageDraft).where(WikiPageDraft.page_id == page_id))
    if draft is not None:
        db.delete(draft)


def _freeze(db: OrmSession, page: WikiPage, author: User | None, note: str = "") -> WikiPageVersion:
    """Write the current state of a page as the next immutable version."""
    page.current_version_number = (page.current_version_number or 0) + 1
    version = WikiPageVersion(
        page_id=page.id,
        number=page.current_version_number,
        title=page.title,
        content_md=page.content_md,
        author_id=author.id if author else None,
        note=(note or "")[:300],
    )
    db.add(version)
    return version


def _wiki_or_404(db: OrmSession, wiki_id: int, user: User | None) -> tuple[Wiki, str | None]:
    wiki = _get_wiki(db, wiki_id)
    role = _require_read(db, wiki, user)
    return wiki, role


# ---------------------------------------------------------------------------
# Wikis
# ---------------------------------------------------------------------------
@router.get("", summary="List the wikis you can read")
def list_wikis(
    request: Request,
    q: str = Query(default="", max_length=120),
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    member_ids: list[int] = []
    if user is not None:
        member_ids = list(
            db.scalars(select(WikiMember.wiki_id).where(WikiMember.user_id == user.id)).all()
        )
    clauses = [Wiki.status == "public"]
    if user is not None:
        clauses.append(Wiki.owner_id == user.id)
        if member_ids:
            clauses.append(Wiki.id.in_(member_ids))
        if user.is_staff:
            clauses.append(Wiki.status == "pending")
    statement = select(Wiki).where(or_(*clauses))
    if mine and user is not None:
        statement = select(Wiki).where(
            or_(Wiki.owner_id == user.id, Wiki.id.in_(member_ids or [-1]))
        )
    if q:
        hits = search.search_wiki_pages(db, q)
        if hits is not None:
            # The search returns page ids; a wiki list has to filter on wiki ids.
            page_ids = {page_id for page_id, _ in hits} or {-1}
            wiki_ids = set(db.scalars(select(WikiPage.wiki_id).where(WikiPage.id.in_(page_ids)))) or {-1}
            statement = statement.where(
                or_(Wiki.id.in_(wiki_ids), Wiki.title.ilike(f"%{q}%"))
            )
        else:
            statement = statement.where(Wiki.title.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(Wiki.updated_at.desc()).limit(limit).offset(offset)).all()
    payload = [_serialise_wiki(db, wiki, _member_role(db, wiki, user), user) for wiki in rows]
    return Response(
        content=json.dumps(payload, default=str),
        media_type="application/json",
        headers={"X-Total-Count": str(total)},
    )


@router.post("", status_code=201, summary="Create a wiki, with its first page")
def create_wiki(
    payload: WikiIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    taken = set(db.scalars(select(Wiki.slug)).all())
    wiki = Wiki(
        owner_id=user.id,
        title=payload.title,
        slug=unique_slug(slugify(payload.title, fallback="wiki"), taken),
        description=payload.description,
        default_language=payload.default_language,
        status="draft",
        canvas={"nodes": [], "edges": []},
    )
    db.add(wiki)
    db.flush()
    # A wiki without a page is a dead end: start with a home page.
    home_title = "Accueil" if payload.default_language == "fr" else "Home"
    page = WikiPage(
        wiki_id=wiki.id,
        slug=slugify(home_title, fallback="home"),
        title=home_title,
        content_md=(
            f"# {wiki.title}\n\n{payload.description}\n\n"
            + (
                "Créez votre première fiche avec **Nouvelle fiche**."
                if payload.default_language == "fr"
                else "Create your first page with **New page**."
            )
        ),
        author_id=user.id,
        position=0,
    )
    db.add(page)
    db.flush()
    _freeze(db, page, user, note="Page created")
    _rebuild_links(db, page)
    db.commit()
    db.refresh(wiki)
    return _serialise_wiki(db, wiki, "owner", user)


@router.get("/search", summary="Full text search across readable wikis")
def search_pages(
    q: str = Query(min_length=1, max_length=120),
    wiki_id: int | None = None,
    scope: str = Query(default="all", pattern="^(all|local)$"),
    limit: int = Query(default=30, ge=1, le=100),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    clauses = [Wiki.status == "public"]
    if user is not None:
        clauses.append(Wiki.owner_id == user.id)
        member_ids = list(
            db.scalars(select(WikiMember.wiki_id).where(WikiMember.user_id == user.id)).all()
        )
        if member_ids:
            clauses.append(Wiki.id.in_(member_ids))
    readable_ids = list(db.scalars(select(Wiki.id).where(or_(*clauses))).all())
    if wiki_id is not None:
        if wiki_id not in readable_ids:
            raise HTTPException(status_code=404, detail="Wiki not found.")
        # "local" keeps the picker inside the wiki being edited; "all" lets an
        # author link a page hosted in another readable (often public) wiki.
        if scope == "local":
            readable_ids = [wiki_id]

    hits = search.search_wiki_pages(db, q, wiki_ids=readable_ids, limit=limit)
    if hits is None:
        rows = db.scalars(
            select(WikiPage)
            .where(
                WikiPage.wiki_id.in_(readable_ids or [-1]),
                or_(WikiPage.title.ilike(f"%{q}%"), WikiPage.content_md.ilike(f"%{q}%")),
            )
            .limit(limit)
        ).all()
        hits = [(page.id, 0.0) for page in rows]

    results = []
    for page_id, score in hits:
        page = db.get(WikiPage, page_id)
        if page is None or page.wiki_id not in readable_ids:
            continue
        wiki = db.get(Wiki, page.wiki_id)
        results.append(
            {
                "page_id": page.id,
                "wiki_id": page.wiki_id,
                "wiki_title": wiki.title if wiki else "",
                "slug": page.slug,
                "title": page.title,
                "excerpt": excerpt(page.content_md, 220),
                "score": round(score, 4),
            }
        )
    return results


@router.get("/{wiki_id}", summary="Wiki metadata, page list and canvas")
def get_wiki(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, role = _wiki_or_404(db, wiki_id, user)
    payload = _serialise_wiki(db, wiki, role, user)
    pages = db.scalars(
        select(WikiPage)
        .where(WikiPage.wiki_id == wiki.id)
        .order_by(WikiPage.position, WikiPage.title)
    ).all()
    payload["pages"] = [_serialise_page(page) for page in pages]
    payload["canvas"] = wiki.canvas or {"nodes": [], "edges": []}
    payload["pending_proposals"] = (
        db.scalar(
            select(func.count(WikiProposal.id))
            .join(WikiPage, WikiPage.id == WikiProposal.page_id)
            .where(WikiPage.wiki_id == wiki.id, WikiProposal.status == "pending")
        )
        or 0
    )
    return payload


# ---------------------------------------------------------------------------
# Import: a whole wiki from an archive, a single page from a markdown file
# ---------------------------------------------------------------------------


def _insert_pages(
    db: OrmSession,
    wiki: Wiki,
    pages: list[ImportedPage],
    user: User,
    *,
    note: str,
) -> int:
    """Add imported pages to a wiki, in order, and wire their links."""
    taken = set(db.scalars(select(WikiPage.slug).where(WikiPage.wiki_id == wiki.id)).all())
    position = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    created = 0
    for imported in pages:
        if position >= MAX_WIKI_PAGES:
            break
        page = WikiPage(
            wiki_id=wiki.id,
            slug=unique_slug(slugify(imported.title, fallback="page"), taken),
            title=imported.title,
            content_md=reflow_markdown(imported.content_md),
            tags=imported.tags,
            position=position,
            author_id=user.id,
        )
        taken.add(page.slug)
        position += 1
        created += 1
        db.add(page)
        db.flush()
        _freeze(db, page, user, note=note)
        _rebuild_links(db, page)
        # An earlier page may already link to this title: adopt the edge now that
        # the target exists, so backlinks work right after the import.
        db.execute(
            update(WikiLink)
            .where(WikiLink.wiki_id == wiki.id, WikiLink.target_slug == page.slug)
            .values(to_page_id=page.id)
        )
    return created


@router.post("/import", status_code=201, summary="Create a wiki from a zip of markdown files")
async def import_archive(
    file: UploadFile = File(..., description="Zip exported from Obsidian, Joplin, or a folder of .md files"),
    title: str = Query(default="", max_length=200),
    visibility: str = Query(default="private", pattern="^(private|public)$"),
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    imported = read_archive(raw, archive_name=file.filename or "")

    wanted = (title or imported.title).strip() or "Imported wiki"
    taken = set(db.scalars(select(Wiki.slug)).all())
    wiki = Wiki(
        owner_id=user.id,
        title=wanted[:200],
        slug=unique_slug(slugify(wanted, fallback="wiki"), taken),
        description=(
            f"Imported from {imported.source} · {len(imported.pages)} page(s)"
        )[:400],
        default_language="en",
        status="draft",
        canvas={"nodes": [], "edges": []},
    )
    db.add(wiki)
    db.flush()
    created = _insert_pages(db, wiki, imported.pages, user, note=f"Imported from {imported.source}")
    if visibility == "public":
        wiki.is_public = bool(user.is_staff)
        wiki.status = "public" if user.is_staff else "pending"
    db.commit()
    db.refresh(wiki)
    return {
        "wiki": {
            "id": wiki.id,
            "title": wiki.title,
            "slug": wiki.slug,
            "status": wiki.status,
            "is_public": wiki.is_public,
            "can_write": True,
        },
        "pages": created,
        "images": imported.images,
        "skipped": imported.skipped,
        "source": imported.source,
    }


@router.post("/{wiki_id}/pages/import", status_code=201, summary="Add a page from a markdown file")
async def import_page(
    wiki_id: int,
    file: UploadFile = File(..., description="One .md file"),
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    imported = parse_markdown_file(raw, file.filename or "page.md")
    total = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    if total >= MAX_WIKI_PAGES:
        raise HTTPException(status_code=422, detail="This wiki has reached its page limit.")
    created = _insert_pages(db, wiki, [imported], user, note="Imported from a markdown file")
    db.commit()
    page = db.scalar(select(WikiPage).where(WikiPage.wiki_id == wiki.id).order_by(WikiPage.position.desc()))
    return {
        "page": _serialise_page(page, with_html=True, pages=_page_slug_map(db, wiki.id)),
        "created": created,
    }


@router.put("/{wiki_id}", summary="Rename or describe a wiki")
def update_wiki(
    wiki_id: int,
    payload: WikiIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    role = _require_write(db, wiki, user)
    wiki.title = payload.title
    wiki.description = payload.description
    wiki.default_language = payload.default_language
    db.commit()
    return _serialise_wiki(db, wiki, role, user)


@router.delete("/{wiki_id}", status_code=204, summary="Delete a wiki and its pages")
def delete_wiki(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    if wiki.owner_id != user.id and not user.is_staff:
        raise HTTPException(status_code=403, detail="Only the owner can delete this wiki.")
    page_ids = list(db.scalars(select(WikiPage.id).where(WikiPage.wiki_id == wiki.id)).all())
    if page_ids:
        db.execute(delete(WikiLink).where(WikiLink.from_page_id.in_(page_ids)))
        db.execute(delete(WikiLink).where(WikiLink.to_page_id.in_(page_ids)))
        db.execute(delete(WikiPageVersion).where(WikiPageVersion.page_id.in_(page_ids)))
        db.execute(delete(WikiReference).where(WikiReference.page_id.in_(page_ids)))
        db.execute(delete(WikiProposal).where(WikiProposal.page_id.in_(page_ids)))
    db.execute(delete(WikiTemplate).where(WikiTemplate.wiki_id == wiki.id))
    db.execute(delete(WikiMember).where(WikiMember.wiki_id == wiki.id))
    db.execute(delete(WikiPage).where(WikiPage.wiki_id == wiki.id))
    db.execute(delete(Wiki).where(Wiki.id == wiki.id))
    db.commit()
    for page_id in page_ids:
        collab.drop(page_id)
    return Response(status_code=204)


@router.post("/{wiki_id}/publish", summary="Publish privately, or publicly when trusted")
def publish_wiki(
    wiki_id: int,
    payload: WikiPublishIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    role = _require_write(db, wiki, user)
    if payload.visibility == "private":
        wiki.status = "private"
        wiki.is_public = False
        db.commit()
        return _serialise_wiki(db, wiki, role, user)

    trusted = user.is_trusted or user.is_staff
    wiki.status = "public" if trusted else "pending"
    wiki.is_public = trusted
    wiki.published_at = utcnow() if trusted else None
    wiki.moderation_note = (
        "" if trusted else "Awaiting administrator review before the public catalogue."
    )
    db.commit()
    return _serialise_wiki(db, wiki, role, user)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@router.get("/{wiki_id}/members", summary="Who else may write here")
def list_members(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki, _ = _wiki_or_404(db, wiki_id, user)
    rows = db.execute(
        select(WikiMember, User)
        .join(User, User.id == WikiMember.user_id)
        .where(WikiMember.wiki_id == wiki.id)
    ).all()
    return [
        {
            "user_id": member.user_id,
            "role": member.role,
            "email": account.email,
            "display_name": account.display_name,
            "since": member.created_at,
        }
        for member, account in rows
    ]


@router.post("/{wiki_id}/members", status_code=201, summary="Invite a maintainer or contributor")
def add_member(
    wiki_id: int,
    payload: WikiMemberIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    if wiki.owner_id != user.id and not user.is_staff:
        raise HTTPException(status_code=403, detail="Only the owner invites members.")
    target = db.scalar(select(User).where(User.email == payload.email))
    if target is None:
        raise HTTPException(status_code=404, detail="No account uses that address.")
    if target.id == wiki.owner_id:
        raise HTTPException(status_code=400, detail="The owner already has full rights.")
    existing = db.scalar(
        select(WikiMember).where(WikiMember.wiki_id == wiki.id, WikiMember.user_id == target.id)
    )
    if existing:
        existing.role = payload.role
    else:
        db.add(WikiMember(wiki_id=wiki.id, user_id=target.id, role=payload.role))
    db.commit()
    return {"user_id": target.id, "role": payload.role}


@router.delete("/{wiki_id}/members/{member_id}", status_code=204, summary="Remove a member")
def remove_member(
    wiki_id: int,
    member_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    if wiki.owner_id != user.id and not user.is_staff:
        raise HTTPException(status_code=403, detail="Only the owner manages members.")
    db.execute(
        delete(WikiMember).where(WikiMember.wiki_id == wiki.id, WikiMember.user_id == member_id)
    )
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Graph and canvas
# ---------------------------------------------------------------------------
@router.get("/{wiki_id}/graph", summary="Link graph of the wiki, for the local graph view")
def wiki_graph(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, _ = _wiki_or_404(db, wiki_id, user)
    pages = db.scalars(select(WikiPage).where(WikiPage.wiki_id == wiki.id)).all()
    by_id = {page.id: page for page in pages}
    nodes = [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "tags": page.tags or [],
            "links": sum(1 for _ in (page.content_md or "").split("[[")) - 1,
        }
        for page in pages
    ]
    edges = []
    seen: set[tuple[int, int]] = set()
    for link in db.scalars(select(WikiLink).where(WikiLink.wiki_id == wiki.id)).all():
        if link.to_page_id and link.to_page_id in by_id:
            key = (link.from_page_id, link.to_page_id)
            if key not in seen:
                seen.add(key)
                edges.append({"source": key[0], "target": key[1], "kind": "link"})

    # Two pages that carry the same tag belong together even without a wikilink:
    # the map then shows the subjects the wiki is made of, not just its clicks.
    by_tag: dict[str, list[int]] = {}
    for page in pages:
        for tag in page.tags or []:
            by_tag.setdefault(tag.strip().lower(), []).append(page.id)
    for tag, ids in by_tag.items():
        for position, source in enumerate(ids):
            for target in ids[position + 1 :]:
                key = (source, target)
                if key in seen or (target, source) in seen:
                    continue
                seen.add(key)
                edges.append({"source": source, "target": target, "kind": "tag", "tag": tag})

    tagged = [node for node in nodes if node["tags"]]
    unresolved = [
        {"slug": link.target_slug, "from": link.from_page_id}
        for link in db.scalars(select(WikiLink).where(WikiLink.wiki_id == wiki.id)).all()
        if link.to_page_id is None and link.target_slug in tagged
    ]
    return {"nodes": nodes, "edges": edges, "unresolved": unresolved}


@router.put("/{wiki_id}/canvas", summary="Store the Obsidian-style canvas")
def save_canvas(
    wiki_id: int,
    payload: WikiCanvasIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)  # raises when the caller may not edit
    canvas = payload.canvas if isinstance(payload.canvas, dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    if len(nodes) > 200 or len(edges) > 400:
        raise HTTPException(status_code=422, detail="Canvas is too large.")
    wiki.canvas = {"nodes": nodes[:200], "edges": edges[:400]}
    db.commit()
    return wiki.canvas


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@router.post("/{wiki_id}/pages", status_code=201, summary="Create a page")
def create_page(
    wiki_id: int,
    payload: WikiPageIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)  # raises when the caller may not edit
    total = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    if total >= MAX_WIKI_PAGES:
        raise HTTPException(status_code=422, detail="This wiki has reached its page limit.")
    taken = set(db.scalars(select(WikiPage.slug).where(WikiPage.wiki_id == wiki.id)).all())
    page = WikiPage(
        wiki_id=wiki.id,
        slug=unique_slug(slugify(payload.title, fallback="page"), taken),
        title=payload.title,
        content_md=reflow_markdown(payload.content_md or f"# {payload.title}\n"),
        tags=payload.tags,
        position=total,
        author_id=user.id,
    )
    db.add(page)
    db.flush()
    _freeze(db, page, user, note=payload.note or "Page created")
    _rebuild_links(db, page)
    # Pages written before this one may already point at its slug: adopt the
    # orphan edges so backlinks work without touching every source page.
    db.execute(
        update(WikiLink)
        .where(WikiLink.wiki_id == wiki.id, WikiLink.target_slug == page.slug)
        .values(to_page_id=page.id)
    )
    db.commit()
    db.refresh(page)
    return _serialise_page(page, with_html=True, pages=_page_slug_map(db, wiki.id))


# ---------------------------------------------------------------------------
# A teaching capsule: five pages that hold a lesson together
# ---------------------------------------------------------------------------
_CAPSULE = {
    "fr": [
        ("Introduction", "# Introduction\n\nPrésentez ici le sujet de la capsule, le public visé et ce que la personne doit savoir faire à la fin.\n\n## Ce que vous allez apprendre\n\n- \n- \n- \n"),
        ("Fiche pédagogique", "# Fiche pédagogique\n\n## Objectifs\n\n- \n\n## Prérequis\n\n- \n\n## Durée et déroulé\n\n| Étape | Durée | Activité |\n| --- | --- | --- |\n|  |  |  |\n\n## Matériel\n\n- \n"),
        ("Cartes personnages", "# Cartes personnages\n\nUne fiche par personnage : nom, rôle, ce qu'il sait, ce qu'il cherche.\n\n## Personnage 1\n\n- Rôle : \n- Atouts : \n- Difficultés : \n"),
        ("Histoire à embranchement", "# Histoire à embranchement\n\nRacontez la situation de départ, puis les choix possibles.\n\nLes questionnaires et les aventures s'insèrent ici avec le bouton « Insérer un questionnaire » de l'éditeur : ils se jouent directement dans la page.\n"),
        ("Pistes de réflexion", "# Pistes de réflexion\n\nCompte tenu des choix faits pendant l'activité et des résultats obtenus, qu'aborderiez-vous lors des prochaines séances ?\n\n- \n- \n"),
    ],
    "en": [
        ("Introduction", "# Introduction\n\nDescribe the topic, the audience, and what the learner should be able to do at the end.\n\n## What you will learn\n\n- \n- \n- \n"),
        ("Lesson plan", "# Lesson plan\n\n## Objectives\n\n- \n\n## Prerequisites\n\n- \n\n## Timing\n\n| Step | Duration | Activity |\n| --- | --- | --- |\n|  |  |  |\n\n## Materials\n\n- \n"),
        ("Character cards", "# Character cards\n\nOne card per character: name, role, what they know, what they want.\n\n## Character 1\n\n- Role: \n- Strengths: \n- Difficulties: \n"),
        ("Branching story", "# Branching story\n\nSet the opening situation, then the possible choices.\n\nQuestionnaires and adventures go here: use the editor's “Insert a questionnaire” button and they play inside the page.\n"),
        ("Reflection prompts", "# Reflection prompts\n\nGiven the choices made during the activity and the results obtained, what would you tackle in the next sessions?\n\n- \n- \n"),
    ],
}


@router.post("/{wiki_id}/capsule", status_code=201, summary="Create the five pages of a teaching capsule")
def create_capsule(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
    lang: str = Query("fr", max_length=8),
) -> dict:
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    pages = _CAPSULE.get(lang.split("-")[0].lower(), _CAPSULE["en"])
    total = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    if total + len(pages) > MAX_WIKI_PAGES:
        raise HTTPException(status_code=422, detail="This wiki has reached its page limit.")
    taken = set(db.scalars(select(WikiPage.slug).where(WikiPage.wiki_id == wiki.id)).all())
    created: list[dict] = []
    previous_id: int | None = None
    for offset, (title, body) in enumerate(pages):
        slug = unique_slug(slugify(title, fallback="page"), taken)
        taken.add(slug)
        page = WikiPage(
            wiki_id=wiki.id,
            slug=slug,
            title=title,
            content_md=reflow_markdown(body),
            tags=[],
            position=total + offset,
            parent_id=previous_id,
            author_id=user.id,
        )
        db.add(page)
        db.flush()
        _freeze(db, page, user, note="Capsule page created")
        _rebuild_links(db, page)
        created.append({"id": page.id, "title": page.title, "slug": page.slug})
        previous_id = page.id
    db.commit()
    return {"items": created, "first_page_id": created[0]["id"] if created else None}


@router.get("/pages/{page_id}", summary="One page, rendered, with backlinks")
def get_page(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    wiki, role = _wiki_or_404(db, page.wiki_id, user)
    payload = _serialise_page(page, with_html=True, pages=_page_slug_map(db, wiki.id))
    payload["backlinks"] = _backlinks(db, page)
    payload["wiki"] = {"id": wiki.id, "title": wiki.title, "status": wiki.status}
    payload["role"] = role
    payload["can_write"] = _writable(role)
    # An editor must know that unsaved typing waits for it; a reader never sees
    # the working copy.
    draft = (
        db.scalar(select(WikiPageDraft).where(WikiPageDraft.page_id == page.id))
        if _writable(role)
        else None
    )
    payload["draft"] = (
        {"length": len(draft.content_md or ""), "updated_at": draft.updated_at}
        if draft and draft.content_md != page.content_md
        else None
    )

    # The reader needs the menu around the page: where it sits, what hangs
    # under it, and which pages it cites or fails to cite.
    siblings = _page_index(db, wiki.id)
    by_id = {
        sibling.id: {
            "id": sibling.id,
            "title": sibling.title,
            "slug": sibling.slug,
            "parent_id": sibling.parent_id,
        }
        for sibling in siblings
    }
    payload["breadcrumb"] = page_breadcrumb(page.id, by_id)
    payload["children"] = [
        {"id": sibling.id, "title": sibling.title, "slug": sibling.slug}
        for sibling in siblings
        if sibling.parent_id == page.id
    ]
    payload["references"] = _references(db, page)
    payload["external_links"] = extract_external_links(page.content_md)
    payload["missing_links"] = _missing_links(db, page)
    payload["editors"] = collab.editors_on(page.id)
    return payload


@router.put("/pages/{page_id}", summary="Save a page (direct write or proposal)")
def save_page(
    page_id: int,
    payload: WikiPageIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    role = _member_role(db, wiki, user)
    if not _readable(wiki, role):
        raise HTTPException(status_code=404, detail="Page not found.")

    if not _writable(role):
        # Readers and contributors never write the live page: their edit lands
        # in the moderation queue, even on a private wiki.
        proposal = WikiProposal(
            page_id=page.id,
            author_id=user.id,
            base_number=page.current_version_number,
            title=payload.title,
            content_md=reflow_markdown(payload.content_md),
            note=payload.note or "Suggested update",
        )

        db.add(proposal)
        db.commit()
        return {
            "status": "proposal",
            "proposal_id": proposal.id,
            "message": "Your update was sent to the wiki owner for review.",
            "page": _serialise_page(page),
        }

    if payload.content_md and len(payload.content_md) > 400_000:
        raise HTTPException(status_code=413, detail="Page is too long.")
    # The placeholder home page is the first thing its author rewrites: give it
    # the slug of its real title. Any later rename keeps the slug, because other
    # pages and links already point at it.
    if page.title != payload.title and page.slug in {"accueil", "home"}:
        taken = set(
            db.scalars(select(WikiPage.slug).where(WikiPage.wiki_id == page.wiki_id)).all()
        )
        taken.discard(page.slug)
        page.slug = unique_slug(slugify(payload.title, fallback="page"), taken)
    page.title = payload.title
    page.content_md = reflow_markdown(payload.content_md)
    page.tags = payload.tags
    version = _freeze(db, page, user, note=payload.note)
    # Publishing ends the working copy: what was typed becomes the page.
    _drop_draft(db, page.id)
    _rebuild_links(db, page)
    db.commit()
    db.refresh(page)
    # Everyone editing this page in real time adopts the saved text, so the
    # version that was just frozen is also what their screen shows.
    collab.reset_room(page.id, page.content_md)
    return {
        "status": "saved",
        "version": version.number,
        "page": _serialise_page(page, with_html=True, pages=_page_slug_map(db, wiki.id)),
    }


@router.delete("/pages/{page_id}/draft", status_code=204, summary="Throw the unsaved draft away")
def discard_draft(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    if not _writable(_member_role(db, wiki, user)):
        raise HTTPException(status_code=403, detail="You cannot edit this page.")
    _drop_draft(db, page.id)
    db.commit()
    # Everybody editing the page goes back to the version that is published.
    collab.reset_room(page.id, page.content_md)


@router.delete("/pages/{page_id}", status_code=204, summary="Delete a page")
def delete_page(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    role = _member_role(db, wiki, user)
    if not _writable(role):
        raise HTTPException(status_code=403, detail="You cannot delete this page.")
    # Children climb one level instead of becoming roots: deleting a section
    # should not silently flatten the menu.
    db.execute(
        update(WikiPage).where(WikiPage.parent_id == page.id).values(parent_id=page.parent_id)
    )
    db.execute(delete(WikiLink).where(WikiLink.from_page_id == page.id))
    db.execute(delete(WikiLink).where(WikiLink.to_page_id == page.id))
    db.execute(delete(WikiPageVersion).where(WikiPageVersion.page_id == page.id))
    db.execute(delete(WikiReference).where(WikiReference.page_id == page.id))
    db.execute(delete(WikiProposal).where(WikiProposal.page_id == page.id))
    db.execute(delete(WikiPage).where(WikiPage.id == page.id))
    db.commit()
    collab.drop(page.id)
    return Response(status_code=204)


def _page_index(db: OrmSession, wiki_id: int) -> list[WikiPage]:
    """Every page of a wiki, in menu order."""
    return list(
        db.scalars(
            select(WikiPage)
            .where(WikiPage.wiki_id == wiki_id)
            .order_by(WikiPage.position, WikiPage.title)
        ).all()
    )


def _reference_out(reference: WikiReference, titles: dict[str, str]) -> dict:
    return {
        "id": reference.id,
        "kind": reference.kind,
        "url": reference.url,
        "host": host_of(reference.url) if reference.url else "",
        "target_slug": reference.target_slug,
        "target_title": titles.get(reference.target_slug, ""),
        "label": reference.label,
        "note": reference.note,
        "created_at": reference.created_at,
    }


def _references(db: OrmSession, page: WikiPage) -> dict:
    """Citations attached to a page, split between outside and inside."""
    titles = {sibling.slug: sibling.title for sibling in _page_index(db, page.wiki_id)}
    rows = db.scalars(
        select(WikiReference)
        .where(WikiReference.page_id == page.id)
        .order_by(WikiReference.position, WikiReference.id)
    ).all()
    external = [_reference_out(row, titles) for row in rows if row.kind == "external"]
    internal = [_reference_out(row, titles) for row in rows if row.kind == "internal"]
    return {"external": external, "internal": internal}


def _missing_links(db: OrmSession, page: WikiPage) -> list[dict]:
    """Targets a page points at that do not exist yet (typos, pages to write)."""
    rows = db.execute(
        select(WikiLink.target_slug)
        .where(WikiLink.from_page_id == page.id, WikiLink.to_page_id.is_(None))
        .distinct()
    ).all()
    return [{"slug": row[0], "title": row[0].replace("-", " ").capitalize()} for row in rows]


def _tree_snapshot(db: OrmSession, wiki: Wiki) -> list[dict]:
    return [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "parent_id": page.parent_id,
            "position": page.position,
        }
        for page in _page_index(db, wiki.id)
    ]


# ---------------------------------------------------------------------------
# Menu tree: order and hierarchy, moved by drag and drop
# ---------------------------------------------------------------------------


MAX_TREE_DEPTH = 6


@router.put("/{wiki_id}/tree", summary="Reorder the menu: order and parents")
def update_tree(
    wiki_id: int,
    payload: WikiTreeIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    pages = _page_index(db, wiki.id)
    by_id = {page.id: page for page in pages}
    if not payload.pages:
        return {"pages": _tree_snapshot(db, wiki)}

    for entry in payload.pages:
        if entry.id not in by_id:
            raise HTTPException(status_code=422, detail="A page in this tree does not exist.")
        if entry.parent_id is not None and entry.parent_id not in by_id:
            raise HTTPException(status_code=422, detail="A parent in this tree does not exist.")
        if entry.parent_id == entry.id:
            raise HTTPException(status_code=422, detail="A page cannot be its own parent.")

    parents = {page.id: page.parent_id for page in pages}
    for entry in payload.pages:
        parents[entry.id] = entry.parent_id

    # A cycle would make the menu unusable and the breadcrumb infinite; a
    # runaway depth would do the same on screen.
    for page_id in parents:
        seen: set[int] = set()
        current: int | None = page_id
        depth = 0
        while current is not None:
            if current in seen:
                raise HTTPException(status_code=422, detail="This move would create a loop.")
            seen.add(current)
            depth += 1
            if depth > MAX_TREE_DEPTH:
                raise HTTPException(status_code=422, detail="The menu is nested too deeply.")
            current = parents.get(current)

    for page_id, parent_id in parents.items():
        by_id[page_id].parent_id = parent_id

    # Positions are renumbered per parent so the order stays dense and stable.
    wanted = {entry.id: entry.position for entry in payload.pages}
    groups: dict[int | None, list[WikiPage]] = {}
    for page in pages:
        groups.setdefault(page.parent_id, []).append(page)
    for siblings in groups.values():
        siblings.sort(key=lambda item: (wanted.get(item.id, item.position), item.id))
        for index, page in enumerate(siblings):
            page.position = index

    db.commit()
    return {"pages": _tree_snapshot(db, wiki)}


# ---------------------------------------------------------------------------
# References: the bibliography of a page, and the wiki-wide index of sources
# ---------------------------------------------------------------------------


@router.get("/pages/{page_id}/references", summary="Citations of a page")
def list_references(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    _wiki_or_404(db, page.wiki_id, user)
    payload = _references(db, page)
    payload["detected"] = extract_external_links(page.content_md)
    payload["missing"] = _missing_links(db, page)
    return payload


@router.post("/pages/{page_id}/references", status_code=201, summary="Cite a source")
def add_reference(
    page_id: int,
    payload: WikiReferenceIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    _require_write(db, wiki, user)
    if payload.kind == "external" and not payload.url:
        raise HTTPException(status_code=422, detail="An external reference needs a URL.")
    if payload.kind == "internal":
        slugs = set(db.scalars(select(WikiPage.slug).where(WikiPage.wiki_id == wiki.id)).all())
        if payload.target_slug not in slugs:
            raise HTTPException(status_code=422, detail="That page does not exist in this wiki.")
    total = (
        db.scalar(select(func.count(WikiReference.id)).where(WikiReference.page_id == page.id)) or 0
    )
    if total >= 200:
        raise HTTPException(status_code=422, detail="This page holds too many references.")
    reference = WikiReference(
        page_id=page.id,
        kind=payload.kind,
        url=payload.url,
        target_slug=payload.target_slug if payload.kind == "internal" else "",
        label=payload.label,
        note=payload.note,
        position=total,
        created_by_id=user.id,
    )
    db.add(reference)
    db.commit()
    db.refresh(reference)
    titles = {sibling.slug: sibling.title for sibling in _page_index(db, wiki.id)}
    return _reference_out(reference, titles)


@router.delete(
    "/pages/{page_id}/references/{reference_id}", status_code=204, summary="Drop a citation"
)
def delete_reference(
    page_id: int,
    reference_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    _require_write(db, wiki, user)
    reference = db.get(WikiReference, reference_id)
    if reference is None or reference.page_id != page.id:
        raise HTTPException(status_code=404, detail="Reference not found.")
    db.delete(reference)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Templates: a wiki's own markdown skeletons
# ---------------------------------------------------------------------------
def _template_out(template: WikiTemplate) -> dict:
    return {
        "id": template.id,
        "wiki_id": template.wiki_id,
        "name": template.name,
        "description": template.description,
        "content_md": template.content_md,
        "keywords": template.keywords or [],
        "updated_at": template.updated_at,
    }


@router.get("/{wiki_id}/templates", summary="Templates of a wiki")
def list_wiki_templates(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, role = _wiki_or_404(db, wiki_id, user)
    if not _readable(wiki, role):
        raise HTTPException(status_code=404, detail="Wiki not found.")
    rows = db.scalars(
        select(WikiTemplate)
        .where(WikiTemplate.wiki_id == wiki.id)
        .order_by(WikiTemplate.position, WikiTemplate.id)
    ).all()
    return [_template_out(row) for row in rows]


@router.post("/{wiki_id}/templates", status_code=201, summary="Create a template")
def create_template(
    wiki_id: int,
    payload: WikiTemplateIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    position = db.scalar(
        select(func.coalesce(func.max(WikiTemplate.position), -1)).where(
            WikiTemplate.wiki_id == wiki.id
        )
    )
    template = WikiTemplate(
        wiki_id=wiki.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        content_md=payload.content_md,
        keywords=[word.strip()[:40] for word in payload.keywords if word.strip()][:20],
        author_id=user.id,
        position=int(position or 0) + 1,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.put("/{wiki_id}/templates/{template_id}", summary="Rewrite a template")
def update_template(
    wiki_id: int,
    template_id: int,
    payload: WikiTemplateIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    template = db.get(WikiTemplate, template_id)
    # The wiki in the path keeps a stray id from editing another wiki's template.
    if template is None or template.wiki_id != wiki_id:
        raise HTTPException(status_code=404, detail="Template not found.")
    wiki = _get_wiki(db, template.wiki_id)
    _require_write(db, wiki, user)
    template.name = payload.name.strip()
    template.description = payload.description.strip()
    template.content_md = payload.content_md
    template.keywords = [word.strip()[:40] for word in payload.keywords if word.strip()][:20]
    template.updated_at = utcnow()
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.delete("/{wiki_id}/templates/{template_id}", status_code=204, summary="Delete a template")
def delete_template(
    wiki_id: int,
    template_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    template = db.get(WikiTemplate, template_id)
    if template is None or template.wiki_id != wiki_id:
        raise HTTPException(status_code=404, detail="Template not found.")
    wiki = _get_wiki(db, template.wiki_id)
    _require_write(db, wiki, user)
    db.delete(template)
    db.commit()
    return Response(status_code=204)


@router.get("/{wiki_id}/references", summary="Every source cited in a wiki")
def wiki_references(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, role = _wiki_or_404(db, wiki_id, user)
    pages = _page_index(db, wiki.id)
    by_id = {page.id: page for page in pages}
    sources: dict[str, dict] = {}

    def remember(url: str, *, label: str, page: WikiPage, stored: bool) -> None:
        entry = sources.setdefault(
            url,
            {
                "url": url,
                "host": host_of(url),
                "label": label,
                "stored": stored,
                "pages": [],
            },
        )
        if label and not entry["label"]:
            entry["label"] = label
        entry["stored"] = entry["stored"] or stored
        if page.id not in {item["id"] for item in entry["pages"]}:
            entry["pages"].append({"id": page.id, "title": page.title, "slug": page.slug})

    for page in pages:
        for link in extract_external_links(page.content_md):
            remember(link["url"], label=link["label"], page=page, stored=False)

    for reference in db.scalars(select(WikiReference).where(WikiReference.kind == "external")).all():
        page = by_id.get(reference.page_id)
        if page is not None:
            remember(reference.url, label=reference.label, page=page, stored=True)

    edges = db.execute(
        select(WikiPage.id, WikiPage.title, WikiPage.slug, WikiLink.target_slug, WikiLink.to_page_id)
        .join(WikiLink, WikiLink.from_page_id == WikiPage.id)
        .where(WikiLink.wiki_id == wiki.id)
    ).all()
    unresolved: dict[str, list[dict]] = {}
    internal: dict[int, dict] = {}
    inbound: dict[int, int] = {}
    for source_id, title, slug, target_slug, to_page_id in edges:
        if to_page_id is None:
            unresolved.setdefault(target_slug, []).append(
                {"id": source_id, "title": title, "slug": slug}
            )
            continue
        target = by_id.get(to_page_id)
        if target is None:
            continue
        internal[target.id] = {
            "id": target.id,
            "title": target.title,
            "slug": target.slug,
            "sources": internal.get(target.id, {}).get("sources", []),
        }
        internal[target.id]["sources"].append({"id": source_id, "title": title, "slug": slug})
        inbound[target.id] = inbound.get(target.id, 0) + 1

    orphans = [
        {"id": page.id, "title": page.title, "slug": page.slug}
        for page in pages
        if inbound.get(page.id, 0) == 0 and page.id != (pages[0].id if pages else None)
    ]
    return {
        "wiki": {"id": wiki.id, "title": wiki.title, "role": role},
        "external": sorted(sources.values(), key=lambda item: (-len(item["pages"]), item["host"])),
        "internal": sorted(internal.values(), key=lambda item: item["title"].lower()),
        "unresolved": [
            {"slug": slug, "title": slug.replace("-", " ").capitalize(), "sources": rows}
            for slug, rows in sorted(unresolved.items())
        ],
        "orphans": orphans,
        "stats": {
            "pages": len(pages),
            "sources": len(sources),
            "internal": len(internal),
            "unresolved": len(unresolved),
            "orphans": len(orphans),
        },
    }


# ---------------------------------------------------------------------------
# Versions, diffs, restore
# ---------------------------------------------------------------------------
def _version_out(version: WikiPageVersion, author: User | None) -> dict:
    return {
        "id": version.id,
        "number": version.number,
        "title": version.title,
        "author": author.display_name if author else None,
        "note": version.note,
        "created_at": version.created_at,
        "size": len(version.content_md or ""),
    }


@router.get("/pages/{page_id}/versions", summary="Version history, newest first")
def list_versions(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    _wiki_or_404(db, page.wiki_id, user)
    rows = db.execute(
        select(WikiPageVersion, User)
        .outerjoin(User, User.id == WikiPageVersion.author_id)
        .where(WikiPageVersion.page_id == page.id)
        .order_by(WikiPageVersion.number.desc())
    ).all()
    return [_version_out(version, author) for version, author in rows]


@router.get("/pages/{page_id}/versions/{number}", summary="One frozen version")
def get_version(
    page_id: int,
    number: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    _wiki_or_404(db, page.wiki_id, user)
    version = db.scalar(
        select(WikiPageVersion).where(
            WikiPageVersion.page_id == page.id, WikiPageVersion.number == number
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return {
        **_version_out(version, db.get(User, version.author_id) if version.author_id else None),
        "content_md": version.content_md,
        "html": render_markdown(version.content_md, pages=_page_slug_map(db, page.wiki_id)),
    }


@router.get("/pages/{page_id}/diff", summary="Line diff between two versions")
def diff_versions(
    page_id: int,
    from_number: int = Query(alias="from", ge=0),
    to_number: int = Query(alias="to", ge=0),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    _wiki_or_404(db, page.wiki_id, user)

    def content(number: int) -> tuple[str, str]:
        if number == 0:
            return ("", "")
        version = db.scalar(
            select(WikiPageVersion).where(
                WikiPageVersion.page_id == page.id, WikiPageVersion.number == number
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail=f"Version {number} not found.")
        return version.title, version.content_md or ""

    old_title, old_md = content(from_number)
    new_title, new_md = content(to_number)
    old_text = f"{old_title}\n{old_md}" if old_title else old_md
    new_text = f"{new_title}\n{new_md}" if new_title else new_md
    rows = unified_diff(old_text, new_text)
    return {
        "from": from_number,
        "to": to_number,
        "rows": rows,
        "stats": diff_stats(rows),
        "side": side_by_side_diff(old_text, new_text),
        "labels": {
            "from": f"v{from_number}",
            "to": f"v{to_number}",
            "page": new_title or old_title or "",
        },
    }


@router.post("/pages/{page_id}/restore/{number}", summary="Copy an old version back")
def restore_version(
    page_id: int,
    number: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    role = _member_role(db, wiki, user)
    if not _writable(role):
        raise HTTPException(status_code=403, detail="You cannot restore this page.")
    version = db.scalar(
        select(WikiPageVersion).where(
            WikiPageVersion.page_id == page.id, WikiPageVersion.number == number
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    page.title = version.title
    page.content_md = version.content_md
    # Restoring is itself a new version: history stays append-only.
    saved = _freeze(db, page, user, note=f"Restored version {number}")
    _drop_draft(db, page.id)
    _rebuild_links(db, page)
    db.commit()
    collab.reset_room(page.id, page.content_md)
    return {"status": "restored", "version": saved.number}


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------
@router.get("/pages/{page_id}/proposals", summary="Pending and past suggestions")
def list_proposals(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki, role = _wiki_or_404(db, page.wiki_id, user)
    statement = select(WikiProposal).where(WikiProposal.page_id == page.id)
    if not _writable(role):
        statement = statement.where(WikiProposal.author_id == user.id)
    rows = db.scalars(statement.order_by(WikiProposal.created_at.desc())).all()
    return [
        {
            "id": proposal.id,
            "title": proposal.title,
            "note": proposal.note,
            "status": proposal.status,
            "author": (db.get(User, proposal.author_id).display_name if proposal.author_id else None),
            "base_number": proposal.base_number,
            "review_note": proposal.review_note,
            "created_at": proposal.created_at,
            "reviewed_at": proposal.reviewed_at,
            "content_md": proposal.content_md if _writable(role) or proposal.author_id == user.id else "",
        }
        for proposal in rows
    ]


@router.post("/pages/{page_id}/proposals", status_code=201, summary="Suggest an update")
def create_proposal(
    page_id: int,
    payload: WikiProposalIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    page = _get_page(db, page_id)
    wiki, role = _wiki_or_404(db, page.wiki_id, user)
    if role is None:
        raise HTTPException(status_code=403, detail="Read access is required to propose.")
    proposal = WikiProposal(
        page_id=page.id,
        author_id=user.id,
        base_number=payload.base_number or page.current_version_number,
        title=payload.title,
        content_md=reflow_markdown(payload.content_md),
        note=payload.note,
    )
    db.add(proposal)
    db.commit()
    return {"id": proposal.id, "status": "pending"}


@router.post("/proposals/{proposal_id}/accept", summary="Accept a suggestion into the live page")
def accept_proposal(
    proposal_id: int,
    payload: WikiReviewIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    proposal = db.get(WikiProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    page = _get_page(db, proposal.page_id)
    wiki = _get_wiki(db, page.wiki_id)
    if not _writable(_member_role(db, wiki, user)):
        raise HTTPException(status_code=403, detail="You cannot review this proposal.")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="This proposal was already reviewed.")
    page.title = proposal.title
    page.content_md = proposal.content_md
    version = _freeze(db, page, user, note=f"Accepted proposal by #{proposal.author_id}")
    _rebuild_links(db, page)
    proposal.status = "accepted"
    proposal.reviewer_id = user.id
    proposal.review_note = payload.note
    proposal.reviewed_at = utcnow()
    db.commit()
    return {"status": "accepted", "version": version.number}


@router.post("/proposals/{proposal_id}/reject", summary="Reject a suggestion")
def reject_proposal(
    proposal_id: int,
    payload: WikiReviewIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    proposal = db.get(WikiProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    page = _get_page(db, proposal.page_id)
    wiki = _get_wiki(db, page.wiki_id)
    if not _writable(_member_role(db, wiki, user)):
        raise HTTPException(status_code=403, detail="You cannot review this proposal.")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="This proposal was already reviewed.")
    proposal.status = "rejected"
    proposal.reviewer_id = user.id
    proposal.review_note = payload.note
    proposal.reviewed_at = utcnow()
    db.commit()
    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get("/pages/{page_id}/export.md", summary="Download one page as markdown")
def export_page(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    wiki, _ = _wiki_or_404(db, page.wiki_id, user)
    slug_map = _page_slug_map(db, wiki.id)
    markdown = rewrite_links_for_export(page.content_md, slug_map)
    body = f"# {page.title}\n\n{markdown}\n"
    filename = f"{page.slug}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{wiki_id}/export.zip", summary="Download the whole wiki as markdown files")
def export_wiki(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, _ = _wiki_or_404(db, wiki_id, user)
    pages = db.scalars(select(WikiPage).where(WikiPage.wiki_id == wiki.id)).all()
    slug_map = _page_slug_map(db, wiki.id)
    entries: list[tuple[str, str, str]] = [
        (page.slug, page.title, rewrite_links_for_export(page.content_md, slug_map))
        for page in pages
    ]
    index = [f"# {wiki.title}", "", wiki.description or "", "", "## Pages", ""]
    index += [f"- [{page.title}]({page.slug}.md)" for page in pages]
    media: dict[str, bytes] = {}
    for page in pages:
        for match in re.finditer(r"/media/([A-Za-z0-9_.\-]+)", page.content_md or ""):
            name = match.group(1)
            candidate = settings.media_dir / name
            if candidate.is_file() and name not in media:
                try:
                    media[name] = candidate.read_bytes()
                except OSError:  # pragma: no cover - racing deletion
                    pass
    payload = build_zip(entries, "\n".join(index) + "\n", media)
    filename = f"{wiki.slug}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _menu_order(pages: list[WikiPage]) -> list[dict]:
    """Flatten the menu tree depth-first, the order the sidebar shows."""
    children: dict[int | None, list[WikiPage]] = {}
    for page in pages:
        children.setdefault(page.parent_id, []).append(page)
    for group in children.values():
        group.sort(key=lambda item: (item.position, item.title.lower()))
    ordered: list[dict] = []
    seen: set[int] = set()

    def walk(parent_id: int | None, depth: int) -> None:
        for page in children.get(parent_id, []):
            if page.id in seen or depth > 6:
                continue
            seen.add(page.id)
            ordered.append({"title": page.title, "markdown": page.content_md or "", "depth": depth})
            walk(page.id, depth + 1)

    walk(None, 0)
    # A page orphaned by a deleted parent still belongs to the export.
    for page in sorted(pages, key=lambda item: item.title.lower()):
        if page.id not in seen:
            ordered.append({"title": page.title, "markdown": page.content_md or "", "depth": 0})
    return ordered


@router.get("/pages/{page_id}/export.pdf", summary="Download one page as a PDF")
def export_page_pdf(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    page = _get_page(db, page_id)
    wiki, _ = _wiki_or_404(db, page.wiki_id, user)
    payload = pdf_export.page_pdf(
        wiki_title=wiki.title,
        page_title=page.title,
        markdown=page.content_md or "",
        footer=f"{wiki.title} — OpenLearn",
    )
    filename = f"{page.slug}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{wiki_id}/export.pdf", summary="Download the whole wiki as a PDF, menu order kept")
def export_wiki_pdf(
    wiki_id: int,
    lang: str = Query(default="en", max_length=5),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, _ = _wiki_or_404(db, wiki_id, user)
    pages = db.scalars(
        select(WikiPage).where(WikiPage.wiki_id == wiki.id).order_by(WikiPage.position, WikiPage.title)
    ).all()
    payload = pdf_export.wiki_pdf(
        wiki_title=wiki.title,
        description=wiki.description or "",
        pages=_menu_order(pages),
        footer=f"{wiki.title} — OpenLearn",
        language=lang,
    )
    filename = f"{wiki.slug}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Questionnaires attached to a wiki
# ---------------------------------------------------------------------------

def _quiz_question_counts(db: OrmSession, quiz_ids: list[int]) -> dict[int, int]:
    if not quiz_ids:
        return {}
    rows = db.execute(
        select(Question.quiz_id, func.count(Question.id))
        .where(Question.quiz_id.in_(quiz_ids))
        .group_by(Question.quiz_id)
    ).all()
    return {quiz_id: count for quiz_id, count in rows}


def _quiz_card(quiz: Quiz, count: int) -> dict:
    return {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description or "",
        "mode": quiz.mode,
        "status": quiz.status,
        "ai_generated": bool(quiz.ai_generated),
        "question_count": count,
        "owner_id": quiz.owner_id,
    }


def _linkable_quiz(db: OrmSession, quiz_id: int, user: User) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Questionnaire not found.")
    if quiz.owner_id != user.id and quiz.status != "public" and not user.is_staff:
        raise HTTPException(status_code=403, detail="That questionnaire is not yours to share.")
    return quiz


@router.get("/{wiki_id}/quizzes", summary="Questionnaires attached to this wiki")
def list_wiki_quizzes(
    wiki_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    wiki, role = _wiki_or_404(db, wiki_id, user)
    _require_read(db, wiki, user)
    quizzes = (
        db.execute(
            select(Quiz)
            .join(WikiQuizLink, WikiQuizLink.quiz_id == Quiz.id)
            .where(WikiQuizLink.wiki_id == wiki.id)
            .order_by(WikiQuizLink.id.desc())
        )
        .scalars()
        .all()
    )
    writable = _writable(role)
    counts = _quiz_question_counts(db, [quiz.id for quiz in quizzes])
    items = [
        _quiz_card(quiz, counts.get(quiz.id, 0))
        for quiz in quizzes
        # A reader must not learn the title of somebody's unpublished draft.
        if writable or quiz.status == "public" or (user is not None and quiz.owner_id == user.id)
    ]
    return {"items": items, "can_manage": writable}


@router.post("/{wiki_id}/quizzes", status_code=201, summary="Attach a questionnaire to this wiki")
def attach_wiki_quiz(
    wiki_id: int,
    payload: WikiQuizLinkIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    quiz = _linkable_quiz(db, payload.quiz_id, user)
    existing = db.scalar(
        select(WikiQuizLink).where(
            WikiQuizLink.wiki_id == wiki.id, WikiQuizLink.quiz_id == quiz.id
        )
    )
    if existing is None:
        db.add(WikiQuizLink(wiki_id=wiki.id, quiz_id=quiz.id, created_by=user.id))
        db.commit()
    counts = _quiz_question_counts(db, [quiz.id])
    return _quiz_card(quiz, counts.get(quiz.id, 0))


@router.delete("/{wiki_id}/quizzes/{quiz_id}", status_code=204, summary="Detach a questionnaire")
def detach_wiki_quiz(
    wiki_id: int,
    quiz_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    db.execute(
        delete(WikiQuizLink).where(
            WikiQuizLink.wiki_id == wiki.id, WikiQuizLink.quiz_id == quiz_id
        )
    )
    db.commit()
    return Response(status_code=204)


@router.post(
    "/{wiki_id}/ai/quiz",
    status_code=201,
    summary="Generate a questionnaire from the wiki content",
)
def generate_quiz_from_wiki(
    wiki_id: int,
    payload: WikiQuizGenerateIn,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    if not wiki_ai.is_configured():
        raise HTTPException(status_code=503, detail="AI assistance is not configured on this instance.")
    wiki = _get_wiki(db, wiki_id)
    _require_write(db, wiki, user)
    enforce_ai_interval(user)

    query = select(WikiPage).where(WikiPage.wiki_id == wiki.id)
    if payload.page_ids:
        query = query.where(WikiPage.id.in_(payload.page_ids))
    pages = db.scalars(query.order_by(WikiPage.position, WikiPage.id)).all()
    source = [
        {"title": page.title, "content_md": page.content_md or ""}
        for page in pages
        if (page.content_md or "").strip()
    ]
    if not source:
        raise HTTPException(status_code=422, detail="This wiki has no written content to work from.")

    try:
        draft = wiki_ai.quiz_from_pages(
            wiki.title,
            source,
            mode=payload.mode,
            count=payload.count,
            language=payload.language,
            brief=payload.brief,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    quiz = Quiz(
        owner_id=user.id,
        title=draft["title"][:120],
        description=draft["description"],
        mode=payload.mode,
        status="draft",
        default_language=payload.language,
        languages=[payload.language],
        ai_generated=True,
    )
    db.add(quiz)
    db.flush()
    for position, question in enumerate(draft["questions"]):
        row = Question(
            quiz_id=quiz.id,
            position=position,
            text_html=f"<p>{escape(question['text'])}</p>",
            time_limit_seconds=30,
            points=100,
        )
        row.options = [
            Option(
                position=option_position,
                text=option["text"],
                is_correct=bool(option["correct"]),
            )
            for option_position, option in enumerate(question["options"])
        ]
        db.add(row)
    db.add(WikiQuizLink(wiki_id=wiki.id, quiz_id=quiz.id, created_by=user.id))
    db.commit()
    return {
        "quiz_id": quiz.id,
        "title": quiz.title,
        "question_count": len(draft["questions"]),
        "mode": quiz.mode,
        "source_pages": len(source),
    }


@router.post("/pages/{page_id}/ai/tags", summary="Propose subject tags for a page")
def suggest_page_tags(
    page_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    if not wiki_ai.is_configured():
        raise HTTPException(status_code=503, detail="AI assistance is not configured on this instance.")
    page = _get_page(db, page_id)
    wiki = _get_wiki(db, page.wiki_id)
    _require_write(db, wiki, user)
    enforce_ai_interval(user)
    used = db.scalars(
        select(WikiPage.tags).where(WikiPage.wiki_id == wiki.id)
    ).all()
    existing: list[str] = []
    for tags in used:
        for tag in tags or []:
            if tag not in existing:
                existing.append(tag)
    try:
        tags = wiki_ai.suggest_tags(
            page.title,
            page.content_md or "",
            language=wiki.default_language or "en",
            existing=existing,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"tags": tags}
