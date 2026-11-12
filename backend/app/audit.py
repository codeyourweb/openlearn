# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""One place where an auditable action is written, and forwarded.

Every security-relevant action ends here, so there is a single answer to "what
do we record, and what do we send to the SIEM?". The row in ``security_events``
is the instance's own trail, shown in the administration page; the same event is
handed to :mod:`log_forward` for an XDR or a SIEM when one is configured.

Two properties matter and are tested:

* recording always succeeds locally — forwarding is best effort and never
  raises, so a collector that is down cannot stop a login from being recorded;
* what is forwarded is built from an explicit vocabulary (actor, target,
  outcome), never from an arbitrary object, so a password cannot travel by
  accident.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session as OrmSession

from . import log_forward
from .deps import client_ip
from .models import SecurityEvent, User


def _actor(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "role": "staff" if user.is_staff else "user",
    }


def record(
    db: OrmSession,
    event: str,
    request: Request | None = None,
    user_id: int | None = None,
    detail: str = "",
    *,
    user: User | None = None,
    target: dict[str, Any] | None = None,
    outcome: str = "success",
    source: str = "api",
    commit: bool = True,
) -> None:
    """Write the local trail, then queue the event for the collector.

    ``commit=False`` lets a router record several events inside one transaction.
    """
    ip = client_ip(request) if request is not None else None
    if user is not None and user_id is None:
        user_id = user.id
    db.add(SecurityEvent(event=event, ip=ip, user_id=user_id, detail=(detail or "")[:300]))
    if commit:
        db.commit()
    log_forward.emit(
        event,
        outcome=outcome,
        actor=_actor(user) or ({"id": user_id} if user_id else None),
        target=target,
        detail={"note": detail} if detail else None,
        ip=ip,
        source=source,
    )


def content(
    db: OrmSession,
    event: str,
    *,
    request: Request | None,
    user: User | None,
    kind: str,
    item_id: Any,
    name: str = "",
    outcome: str = "success",
    detail: str = "",
    commit: bool = True,
) -> None:
    """A content action: created, updated, deleted, published.

    The name travels because a human triaging an alert needs to know *which*
    quiz a deletion touched; it is bounded and stripped of control characters by
    :func:`log_forward.clean_text`.
    """
    record(
        db,
        event,
        request,
        None,
        "",
        user=user,
        target={"type": kind, "id": item_id, "name": name},
        outcome=outcome,
        commit=False,
        source="content",
    )
    if commit:
        db.commit()
