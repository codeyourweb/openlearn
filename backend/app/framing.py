# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""How an author framed a picture inside its display area.

An illustration is rarely the shape of the frame that shows it: a 2:3 card, a
wide scene banner, a square thumbnail. Rather than crop once and for ever, the
author chooses what stays visible — a focus point and a zoom — and the page
applies it. ``{}`` means "no framing": the picture is shown whole, which is the
default and the behaviour every existing image keeps.
"""

from __future__ import annotations

from typing import Any

# Zoom beyond 3 crops more than half the picture away; below 1 there is nothing
# to zoom out of, since the frame is already filled.
MIN_ZOOM = 1.0
MAX_ZOOM = 3.0


def normalize_framing(value: Any) -> dict[str, float]:
    """Return a clean framing dict, or ``{}`` for "show the whole picture"."""
    if not isinstance(value, dict):
        return {}
    try:
        x = float(value.get("x", 50))
        y = float(value.get("y", 50))
        zoom = float(value.get("zoom", 1))
    except (TypeError, ValueError):
        return {}
    x = min(100.0, max(0.0, x))
    y = min(100.0, max(0.0, y))
    zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
    # Centred and unzoomed is the default rendering: storing it would only make
    # every payload noisier.
    if abs(x - 50) < 0.05 and abs(y - 50) < 0.05 and zoom < 1.005:
        return {}
    return {"x": round(x, 1), "y": round(y, 1), "zoom": round(zoom, 2)}


def framing_payload(value: Any) -> dict[str, float] | None:
    """What the API returns: the framing, or ``None`` when there is none."""
    framing = normalize_framing(value)
    return framing or None
