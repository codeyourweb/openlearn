# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""WebSocket feed for live co-editing of one wiki page.

A client sends splices and cursors; the server rebases them and fans them out.
Readers may connect too: they see the text move and the caret of each editor,
but their own operations are refused — the moderation rule of the REST API
applies to the socket as well.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .. import collab
from ..config import settings
from ..db import SessionLocal
from ..models import User, Wiki, WikiPage, WikiPageDraft, utcnow
from ..security import decode_access_token
from ..wiki import rebuild_links
from .wiki import _member_role, _readable, _writable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


def draft_for(db, page_id: int) -> WikiPageDraft | None:
    return db.scalar(select(WikiPageDraft).where(WikiPageDraft.page_id == page_id))


def persist_live(page_id: int, content: str, author_id: int | None = None) -> None:
    """Park the typed text in the page's draft; never publish it.

    Called from a worker thread by the room once the typing stops. The version
    history stays the record of deliberate saves, and the published page keeps
    showing its last saved version until somebody presses Save. Before this,
    stopping to type was enough to rewrite what every reader saw.
    """
    with SessionLocal() as db:
        page = db.get(WikiPage, page_id)
        if page is None:
            return
        draft = draft_for(db, page_id)
        if draft is None:
            # Nothing to keep if the text is the published one.
            if page.content_md == content:
                return
            draft = WikiPageDraft(page_id=page_id, content_md=content)
            db.add(draft)
        elif draft.content_md == content:
            return
        draft.content_md = content
        draft.updated_by = author_id
        draft.updated_at = utcnow()
        db.commit()


collab.configure_persist(persist_live)


def _user_from_socket(websocket: WebSocket, db) -> User | None:
    cookie = websocket.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    payload = decode_access_token(cookie)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return db.get(User, user_id)


@router.websocket("/pages/{page_id}/live")
async def live_page(websocket: WebSocket, page_id: int):
    db = SessionLocal()
    client: collab.Client | None = None
    room: collab.CollabRoom | None = None
    try:
        page = db.get(WikiPage, page_id)
        if page is None:
            await websocket.close(code=4404, reason="Page not found")
            return
        wiki = db.get(Wiki, page.wiki_id)
        if wiki is None:
            await websocket.close(code=4404, reason="Page not found")
            return
        user = _user_from_socket(websocket, db)
        role = _member_role(db, wiki, user) if user else None
        # Reading anonymously works on a public wiki, but presence carries a
        # name and a caret: that needs an identity.
        if not _readable(wiki, role) or user is None:
            await websocket.close(code=4401, reason="Authentication required")
            return

        await websocket.accept()
        collab.bind_loop()
        draft = draft_for(db, page.id)
        room = collab.room_for(page.id, draft.content_md if draft else page.content_md)
        client = collab.Client(
            client_id=uuid.uuid4().hex[:12],
            user_id=user.id,
            name=user.display_name or user.email,
            color=collab.color_for(user.id, user.display_name or ""),
            can_write=_writable(role),
            websocket=websocket,
        )
        room.clients[client.client_id] = client
        await websocket.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "client_id": client.client_id,
                    "rev": room.rev,
                    "content": room.content,
                    "version": page.current_version_number,
                    "can_write": client.can_write,
                    "me": client.as_dict(),
                    "users": room.users(),
                },
                ensure_ascii=False,
            )
        )
        # Everybody else learns about the newcomer, and the newcomer already
        # knows who is there from its hello.
        await room.broadcast({"type": "presence", "users": room.users()}, skip=client.client_id)

        while True:
            raw = await websocket.receive_text()
            if raw == "ping":
                await websocket.send_text('{"type":"pong"}')
                continue
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")

            if kind == "cursor":
                client.anchor = max(0, int(message.get("anchor") or 0))
                client.head = max(0, int(message.get("head") or client.anchor))
                await room.broadcast(
                    {
                        "type": "cursor",
                        "client_id": client.client_id,
                        "user_id": client.user_id,
                        "name": client.name,
                        "color": client.color,
                        "anchor": client.anchor,
                        "head": client.head,
                    },
                    skip=client.client_id,
                )
                continue

            if kind != "op":
                continue
            if not client.can_write:
                await websocket.send_text(
                    json.dumps({"type": "denied", "reason": "read-only"})
                )
                continue
            text = message.get("text")
            if not isinstance(text, str):
                continue
            try:
                base_rev = int(message.get("rev", 0))
            except (TypeError, ValueError):
                continue
            room.note_author(client.user_id)
            outcome = room.apply_text(base_rev, text)
            if outcome == collab.NO_CHANGE:
                # The author already shows exactly what the room holds: an answer
                # would only make the client rebuild its surface under the caret.
                continue
            if outcome is None:
                await websocket.send_text(
                    json.dumps(
                        {"type": "resync", "rev": room.rev, "content": room.content},
                        ensure_ascii=False,
                    )
                )
                continue
            rev, pos, delete, insert, conflicted = outcome
            await room.broadcast(
                {
                    "type": "op",
                    "rev": rev,
                    "pos": pos,
                    "delete": delete,
                    "insert": insert,
                    "client_id": client.client_id,
                    "user_id": client.user_id,
                    "name": client.name,
                    "color": client.color,
                    "conflict": conflicted,
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - a socket must never take the worker down
        logger.exception("Live editing socket failed for page %s", page_id)
    finally:
        if room is not None and client is not None:
            room.clients.pop(client.client_id, None)
            try:
                await room.broadcast({"type": "presence", "users": room.users()})
            except Exception:  # noqa: BLE001
                pass
        db.close()