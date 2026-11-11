# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Solo play-throughs of branching ("adventure") quizzes.

A run is created from a published quiz (or from one's own draft), snapshots the
validated graph, and is then driven one choice at a time. The token is a
capability: it is stored hashed and only ever lives in the visitor's browser,
exactly like participant tokens on live sessions.

Adventure quizzes are solo by design: there is no lobby, no PIN and no timer.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import adventure as engine
from ..content import FALLBACK_LANGUAGE, valid_language
from ..db import get_db
from ..deps import enforce_rate_limit, get_optional_user, require_user
from ..game import aware
from ..models import AdventureRun, Quiz, SecurityEvent, User, utcnow
from ..sanitize import html_to_text
from ..schemas import AdventureChooseIn, AdventureRunIn

router = APIRouter(prefix="/api/v1/adventure", tags=["adventure"])

RUN_TOKEN_HEADER = "X-Run-Token"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_run(db: OrmSession, token: str) -> AdventureRun:
    run = db.scalar(select(AdventureRun).where(AdventureRun.token_hash == _hash(token)))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def _public_view(quiz: Quiz, user: User | None) -> bool:
    if quiz.status == "public":
        return True
    if user is None:
        return False
    return quiz.owner_id == user.id or user.is_staff


def _arm_clock(run: AdventureRun, snapshot: dict, now: datetime | None = None) -> None:
    """Set the deadline of the scene the run is about to show."""
    mode = snapshot.get("timer_mode") or "none"
    limit = int(snapshot.get("time_limit_seconds") or 0)
    now = now or utcnow()
    if mode == "none" or limit <= 0:
        run.node_deadline = None
        run.run_deadline = None
        return
    if mode == "global":
        if run.run_deadline is None:
            run.run_deadline = now + timedelta(seconds=limit)
        run.node_deadline = run.run_deadline
        return
    run.node_deadline = now + timedelta(seconds=limit)


def _state(run: AdventureRun, snapshot: dict) -> dict:
    attributes = []
    for attribute in snapshot["attributes"]:
        attributes.append(
            {
                "key": attribute["key"],
                "label": attribute["label"],
                "value": run.attributes.get(attribute["key"], attribute["initial"]),
                "initial": attribute["initial"],
                "min": attribute["min"],
                "max": attribute["max"],
            }
        )

    payload = {
        "run": {
            "status": run.status,
            "language": run.language,
            "steps": len(run.path or []),
            "node_deadline": _iso(run.node_deadline),
            "timer_mode": snapshot.get("timer_mode") or "none",
            "timeout_effect": snapshot.get("timeout_effect") or "penalty",
        },
        "attributes": attributes,
        "node": None,
        "finished": run.status == "finished",
        "ending": None,
    }

    if run.status == "finished":
        # An ending node owns a scene like any other: the text written in the
        # "step text" field is the picture the reader lands on, and the outcome
        # text closes the story. Death and victory endings have no such node, so
        # only the closing text is shown there.
        node = (snapshot.get("nodes") or {}).get(run.ending_key or "") or {}
        reaching_node = node.get("kind") == "ending"
        scene = (node.get("text") or "") if reaching_node else ""
        payload["ending"] = {
            "kind": run.ending_kind or "exit",
            "scene_html": scene,
            "scene_plain": html_to_text(scene),
            "text_html": run.outcome_text_html or "",
            "text_plain": html_to_text(run.outcome_text_html or ""),
            "image_path": node.get("image") if reaching_node else None,
            "image_framing": (node.get("framing") or None) if reaching_node else None,
            "background_path": run.background_path
            or ((node.get("background") or None) if reaching_node else None),
            "attribute": (run.path or [{}])[-1].get("ending_attribute", "") if run.path else "",
        }
        return payload

    node = (snapshot.get("nodes") or {}).get(run.current_key)
    if node is None:
        raise HTTPException(status_code=409, detail="This run points to a missing node.")
    payload["node"] = {
        "key": node["key"],
        "kind": node["kind"],
        "text_html": node["text"],
        "text_plain": html_to_text(node["text"]),
        "image_path": node.get("image"),
        "image_framing": node.get("framing") or None,
        "background_path": node.get("background"),
        "choices": [{"key": choice["key"], "text": choice["text"]} for choice in node["choices"]],
    }
    return payload


def _playable_snapshot(db: OrmSession, run: AdventureRun) -> dict:
    """The story this run plays.

    A reader keeps the story they started, whatever the author does to it
    afterwards: that is what the snapshot is for. The author's own preview is the
    exception — its only purpose is to show the document as it is now, so it is
    rebuilt when the quiz has changed since the run began. The place and the
    counters survive when the scene and the attributes still exist.
    """
    snapshot = run.snapshot or {}
    if run.status == "finished" or run.user_id is None:
        return snapshot
    quiz = db.get(Quiz, run.quiz_id)
    if quiz is None or quiz.owner_id != run.user_id:
        return snapshot

    current = engine.build_snapshot(quiz, run.language)
    if not current["start"] or current["start"] not in current["nodes"]:
        return snapshot
    if current.get("revision") == snapshot.get("revision"):
        return snapshot

    known = {attribute["key"]: attribute for attribute in current["attributes"]}
    values = {key: value for key, value in (run.attributes or {}).items() if key in known}
    for key, attribute in known.items():
        values.setdefault(key, attribute["initial"])
    run.attributes = values
    if run.current_key not in current["nodes"]:
        run.current_key = current["start"]
    run.snapshot = current
    run.updated_at = utcnow()
    _arm_clock(run, current)
    db.commit()
    db.refresh(run)
    return current


@router.post("/quizzes/{quiz_id}/runs", status_code=status.HTTP_201_CREATED)
def start_run(
    quiz_id: int,
    payload: AdventureRunIn,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    enforce_rate_limit(request, "adventure-start", limit=30, window=60)
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.mode != "adventure":
        raise HTTPException(status_code=404, detail="Adventure quiz not found.")
    if not _public_view(quiz, user):
        raise HTTPException(status_code=403, detail="This quiz is not published yet.")

    language = payload.language if valid_language(payload.language) else quiz.default_language
    snapshot = engine.build_snapshot(quiz, language)
    if not snapshot["start"] or snapshot["start"] not in snapshot["nodes"]:
        raise HTTPException(status_code=409, detail="This story has no valid start node.")

    token = secrets.token_urlsafe(32)
    run = AdventureRun(
        quiz_id=quiz.id,
        user_id=user.id if user else None,
        token_hash=_hash(token),
        language=language or FALLBACK_LANGUAGE,
        snapshot=snapshot,
        attributes=engine.initial_attributes(snapshot),
        current_key=snapshot["start"],
        path=[],
        status="active",
    )
    _arm_clock(run, snapshot)
    db.add(run)
    db.add(
        SecurityEvent(
            event="adventure_start",
            ip=request.client.host if request.client else None,
            user_id=user.id if user else None,
            detail=f"quiz={quiz.id}",
        )
    )
    db.commit()
    db.refresh(run)
    return {"run_token": token, "state": _state(run, snapshot)}


@router.get("/runs/{token}")
def get_run(
    token: str,
    request: Request,
    db: OrmSession = Depends(get_db),
):
    enforce_rate_limit(request, "adventure-state", limit=240, window=60)
    run = _get_run(db, token)
    return _state(run, _playable_snapshot(db, run))


@router.post("/runs/{token}/timeout")
def expire_scene(
    token: str,
    request: Request,
    db: OrmSession = Depends(get_db),
    run_header: str | None = Header(default=None, alias=RUN_TOKEN_HEADER),
):
    """The clock on the current scene ran out.

    The client asks, the server decides: if its own deadline has not passed yet,
    nothing happens. A penalty or an early death is then applied exactly once.
    """
    enforce_rate_limit(request, "adventure-timeout", limit=60, window=60)
    if run_header and run_header != token:
        raise HTTPException(status_code=403, detail="Token mismatch.")
    run = _get_run(db, token)
    if run.status == "finished":
        return _state(run, run.snapshot or {})
    snapshot = _playable_snapshot(db, run)
    if (snapshot.get("timer_mode") or "none") == "none":
        raise HTTPException(status_code=409, detail="This story has no timer.")
    deadline = aware(run.node_deadline)
    if deadline is not None and utcnow() < deadline:
        raise HTTPException(status_code=409, detail="Time is not up yet.")

    result = engine.apply_timeout(snapshot, run.attributes or {}, run.current_key)
    run.attributes = result["attributes"]
    run.path = list(run.path or []) + [{"node": run.current_key, "choice": "__timeout__"}]
    run.updated_at = utcnow()
    if result["finished"]:
        run.status = "finished"
        run.ending_kind = result["ending_kind"]
        run.ending_key = result["ending_key"] or None
        run.outcome_text_html = result["outcome_text"] or ""
        run.background_path = result["background"]
        run.finished_at = utcnow()
        run.node_deadline = None
    else:
        _arm_clock(run, snapshot)
    db.commit()
    db.refresh(run)
    return _state(run, snapshot)


@router.post("/runs/{token}/choose")
def choose(
    token: str,
    payload: AdventureChooseIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    run_header: str | None = Header(default=None, alias=RUN_TOKEN_HEADER),
):
    enforce_rate_limit(request, "adventure-choose", limit=120, window=60)
    if run_header and run_header != token:
        raise HTTPException(status_code=403, detail="Token mismatch.")
    run = _get_run(db, token)
    if run.status == "finished":
        raise HTTPException(status_code=409, detail="This run is already finished.")

    snapshot = _playable_snapshot(db, run)
    try:
        result = engine.take_choice(snapshot, run.attributes or {}, run.current_key, payload.choice)
    except engine.AdventureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run.attributes = result["attributes"]
    run.path = list(run.path or []) + [
        {"node": result["path"][0]["node"], "choice": result["path"][0]["choice"]}
    ]
    run.updated_at = utcnow()

    if result["finished"]:
        run.status = "finished"
        run.ending_kind = result["ending_kind"]
        run.ending_key = result["ending_key"] or None
        run.outcome_text_html = result["outcome_text"] or ""
        run.background_path = result["background"]
        run.finished_at = utcnow()
        if result.get("ending_attribute"):
            run.path = run.path[:-1] + [
                {**run.path[-1], "ending_attribute": result["ending_attribute"]}
            ]
    else:
        run.current_key = result["current"]
        _arm_clock(run, snapshot)

    db.commit()
    db.refresh(run)
    return _state(run, snapshot)


@router.get("/quizzes/{quiz_id}/runs")
def my_runs(
    quiz_id: int,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """The signed-in visitor's own play-throughs of one adventure."""
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.mode != "adventure":
        raise HTTPException(status_code=404, detail="Adventure quiz not found.")
    runs = db.scalars(
        select(AdventureRun)
        .where(AdventureRun.quiz_id == quiz_id, AdventureRun.user_id == user.id)
        .order_by(AdventureRun.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": run.id,
            "status": run.status,
            "ending_kind": run.ending_kind,
            "language": run.language,
            "attributes": run.attributes,
            "steps": len(run.path or []),
            "created_at": run.created_at,
            "finished_at": run.finished_at,
        }
        for run in runs
    ]
