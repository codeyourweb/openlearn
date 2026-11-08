# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Branching ("adventure") quizzes: graph validation, snapshot and run engine.

The editor saves the whole story as one document (attributes, nodes, choices,
effects, outcomes). Everything is validated here before it is written, and the
validated graph is snapshotted into each run so that editing a story never
changes a play-through already in progress.

This module is pure: it takes plain dicts and Pydantic models, never touches the
database, and therefore stays trivially testable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MAX_NODES = 200
MAX_ATTRIBUTES = 12
MAX_CHOICES = 8
MAX_EFFECTS = 12


class AdventureError(ValueError):
    """Raised when a story graph is not playable."""


def slug_key(value: Any, *, limit: int = 60) -> str:
    """Turn written words into a usable technical key.

    Adventure authors write "Points forts" or "courage équestre" in a field meant
    for an identifier, and used to be answered with an English message about
    letters, digits and underscores. The key is internal: it is derived from what
    was written instead of refusing the words. The browser implements the same
    rule, so both sides agree on what a label becomes.
    """
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", stripped).strip("-_").lower()
    return (slug or "item")[:limit]


def _text(entity: Any, field: str) -> str:
    """Read ``field`` from a Pydantic model or a dict."""
    return getattr(entity, field, None) if not isinstance(entity, dict) else entity.get(field)


def validate_adventure_graph(graph: Any, strict: bool = False) -> None:
    """Reject graphs that are structurally broken, and optionally unplayable ones.

    Structural problems (duplicate keys, dangling targets, a start node that is
    not a question, out-of-range attribute bounds) are always rejected: they
    would break the runtime. ``strict`` additionally rejects a story nobody can
    finish — unreachable nodes and a start node that leads to no ending — which
    is fine while the author is still drawing it in the editor but never fine
    for a published story.
    """
    nodes = list(_text(graph, "nodes") or [])
    attributes = list(_text(graph, "attributes") or [])
    start = (_text(graph, "start") or "").strip()

    if not nodes:
        raise AdventureError("A story needs at least one node.")
    if not attributes:
        raise AdventureError("A story needs at least one attribute.")

    node_keys: list[str] = [(_text(n, "key") or "").strip() for n in nodes]
    if len(set(node_keys)) != len(node_keys):
        raise AdventureError("Node keys must be unique.")
    node_by_key = {key: node for key, node in zip(node_keys, nodes, strict=True)}

    attr_keys: list[str] = [(_text(a, "key") or "").strip() for a in attributes]
    if len(set(attr_keys)) != len(attr_keys):
        raise AdventureError("Attribute keys must be unique.")

    if start not in node_by_key:
        raise AdventureError("The start node must exist.")
    if _text(node_by_key[start], "kind") != "question":
        raise AdventureError("The start node must be a question.")

    for attribute in attributes:
        key = _text(attribute, "key")
        low, high = _text(attribute, "min_value"), _text(attribute, "max_value")
        if low is not None and high is not None and low > high:
            raise AdventureError(f"Attribute '{key}': minimum is above maximum.")
        death, victory = _text(attribute, "death_at_or_below"), _text(attribute, "victory_at_or_above")
        if death is not None and victory is not None and death >= victory:
            raise AdventureError(
                f"Attribute '{key}': the death threshold must stay below the victory threshold."
            )
        initial = _text(attribute, "initial_value")
        if low is not None and initial < low:
            raise AdventureError(f"Attribute '{key}': initial value is below its minimum.")
        if high is not None and initial > high:
            raise AdventureError(f"Attribute '{key}': initial value is above its maximum.")

    has_ending = False
    for key, node in node_by_key.items():
        kind = _text(node, "kind")
        choices = list(_text(node, "choices") or [])
        outcomes = list(_text(node, "outcomes") or [])

        if kind == "ending":
            has_ending = True
            if choices:
                raise AdventureError(f"Ending node '{key}' cannot have choices.")
            if not outcomes:
                raise AdventureError(f"Ending node '{key}' needs at least one ending text.")
            for outcome in outcomes:
                _validate_outcome(outcome, attr_keys, key)
            continue

        if not 2 <= len(choices) <= MAX_CHOICES:
            raise AdventureError(
                f"Node '{key}' needs between 2 and {MAX_CHOICES} choices."
            )
        seen: set[str] = set()
        for choice in choices:
            choice_key = (_text(choice, "key") or "").strip()
            if choice_key in seen:
                raise AdventureError(f"Node '{key}': choice keys must be unique.")
            seen.add(choice_key)
            target = _text(choice, "target")
            if target and target not in node_by_key:
                raise AdventureError(
                    f"Node '{key}': choice '{choice_key}' points to unknown node '{target}'."
                )
            effects = list(_text(choice, "effects") or [])
            if len(effects) > MAX_EFFECTS:
                raise AdventureError(f"Choice '{choice_key}' has too many effects.")
            for effect in effects:
                attribute = _text(effect, "attribute")
                if attribute not in attr_keys:
                    raise AdventureError(
                        f"Choice '{choice_key}' affects unknown attribute '{attribute}'."
                    )

    if not has_ending:
        raise AdventureError("A story needs at least one ending node.")

    # Every node must be reachable from the start and at least one ending must
    # be, otherwise the story contains work the visitor can never see.
    reachable: set[str] = set()
    stack = [start]
    while stack:
        key = stack.pop()
        if key in reachable:
            continue
        reachable.add(key)
        node = node_by_key[key]
        for choice in list(_text(node, "choices") or []):
            target = _text(choice, "target")
            if target:
                stack.append(target)
    if not strict:
        return

    unreachable = sorted(set(node_keys) - reachable)
    if unreachable:
        raise AdventureError(f"Unreachable nodes: {', '.join(unreachable[:5])}.")

    reachable_endings = [k for k in reachable if _text(node_by_key[k], "kind") == "ending"]
    terminal_choices = any(
        not _text(choice, "target")
        for key in reachable
        for choice in list(_text(node_by_key[key], "choices") or [])
    )
    if not reachable_endings and not terminal_choices:
        raise AdventureError("No ending can be reached from the start node.")


def _validate_outcome(outcome: Any, attr_keys: list[str], node_key: str) -> None:
    kind = _text(outcome, "kind")
    attribute = _text(outcome, "attribute")
    if kind in ("highest", "lowest", "range"):
        if not attribute:
            raise AdventureError(f"Ending '{node_key}': an ending text needs an attribute.")
        if attribute not in attr_keys:
            raise AdventureError(
                f"Ending '{node_key}': unknown attribute '{attribute}'."
            )
    if kind == "range":
        low, high = _text(outcome, "range_min"), _text(outcome, "range_max")
        if low is None or high is None:
            raise AdventureError(f"Ending '{node_key}': a range needs both bounds.")
        if low > high:
            raise AdventureError(f"Ending '{node_key}': range minimum is above maximum.")


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------



def build_snapshot(quiz: Any, language: str | None = None) -> dict:
    """Freeze a playable, already-translated copy of the story."""
    language = language or getattr(quiz, "default_language", "en") or "en"
    settings = getattr(quiz, "adventure_settings", None) or {}

    attributes = []
    for attribute in getattr(quiz, "adventure_attributes", []):
        attributes.append(
            {
                "key": attribute.key,
                "label": attribute.label_translations.get(language) or attribute.label,
                "initial": attribute.initial_value,
                "min": attribute.min_value,
                "max": attribute.max_value,
                "death_at_or_below": attribute.death_at_or_below,
                "victory_at_or_above": attribute.victory_at_or_above,
            }
        )

    nodes: dict[str, dict] = {}
    for node in getattr(quiz, "adventure_nodes", []):
        choices = [
            {
                "key": choice.key,
                "text": choice.text_translations.get(language) or choice.text,
                "target": choice.target_key or "",
                "effects": {effect.attribute_key: effect.delta for effect in choice.effects},
            }
            for choice in node.choices
        ]
        outcomes = [
            {
                "kind": outcome.kind,
                "attribute": outcome.attribute_key,
                "range_min": outcome.range_min,
                "range_max": outcome.range_max,
                "text": outcome.text_translations.get(language) or outcome.text_html,
                "priority": outcome.priority,
            }
            for outcome in sorted(node.outcomes, key=lambda item: item.priority)
        ]
        nodes[node.key] = {
            "key": node.key,
            "kind": node.kind,
            "text": node.text_translations.get(language) or node.text_html,
            "image": node.image_path,
            "background": node.background_path,
            "choices": choices,
            "outcomes": outcomes,
        }

    def setting(name: str) -> str:
        field = settings.get(name) or ""
        if isinstance(field, dict):
            return field.get(language) or field.get("en") or ""
        return field

    return {
        "language": language,
        "start": getattr(quiz, "adventure_start_key", "") or "",
        "attributes": attributes,
        "nodes": nodes,
        "death_text": setting("death_text_html"),
        "victory_text": setting("victory_text_html"),
        "death_background": settings.get("death_background_path") or None,
        "victory_background": settings.get("victory_background_path") or None,
        "timer_mode": settings.get("timer_mode") or "none",
        "time_limit_seconds": int(settings.get("time_limit_seconds") or 0),
        "timeout_effect": settings.get("timeout_effect") or "penalty",
        "timeout_penalty": int(settings.get("timeout_penalty") or 1),
        "timeout_penalty_attribute": settings.get("timeout_penalty_attribute") or "",
    }


def initial_attributes(snapshot: dict) -> dict[str, int]:
    return {attribute["key"]: attribute["initial"] for attribute in snapshot["attributes"]}


def _clamp(value: int, attribute: dict) -> int:
    if attribute.get("min") is not None:
        value = max(value, attribute["min"])
    if attribute.get("max") is not None:
        value = min(value, attribute["max"])
    return value


def check_end_conditions(snapshot: dict, values: dict[str, int]) -> tuple[str, str] | None:
    """Return ``(kind, attribute)`` when a threshold is crossed, else ``None``."""
    for attribute in snapshot["attributes"]:
        value = values.get(attribute["key"], 0)
        death = attribute.get("death_at_or_below")
        victory = attribute.get("victory_at_or_above")
        if death is not None and value <= death:
            return ("death", attribute["key"])
        if victory is not None and value >= victory:
            return ("victory", attribute["key"])
    return None


def resolve_outcome(node: dict, values: dict[str, int]) -> str:
    """Pick the ending text that matches the visitor's final attributes."""
    outcomes = list(node.get("outcomes") or [])
    if not outcomes:
        return ""
    ranked = [(key, value) for key, value in values.items()]
    ranked.sort(key=lambda item: item[1], reverse=True)
    highest = ranked[0][0] if ranked else None
    lowest = ranked[-1][0] if ranked else None

    for outcome in sorted(outcomes, key=lambda item: item.get("priority") or 0):
        kind = outcome.get("kind")
        attribute = outcome.get("attribute")
        if kind == "default":
            return outcome.get("text") or ""
        if kind == "highest" and attribute == highest:
            return outcome.get("text") or ""
        if kind == "lowest" and attribute == lowest:
            return outcome.get("text") or ""
        if kind == "range":
            value = values.get(attribute or "", 0)
            low, high = outcome.get("range_min"), outcome.get("range_max")
            if low is not None and high is not None and low <= value <= high:
                return outcome.get("text") or ""
    return ""


def apply_timeout(snapshot: dict, values: dict[str, int], node_key: str) -> dict:
    """The clock ran out on ``node_key``.

    The author chose between a penalty (an attribute drops, which may itself
    trip a death threshold) and an immediate early death. Nothing here is a
    "game over by timer" for a story that never opted into a clock.
    """
    effect = snapshot.get("timeout_effect") or "penalty"
    path_entry = {"node": node_key, "choice": "__timeout__"}

    if effect == "death":
        return {
            "finished": True,
            "ending_kind": "death",
            "ending_key": "",
            "ending_attribute": snapshot.get("timeout_penalty_attribute") or "",
            "ending_label": "",
            "attributes": dict(values),
            "path": [path_entry],
            "outcome_text": snapshot.get("death_text") or "",
            "background": snapshot.get("death_background"),
            "timed_out": True,
        }

    by_key = {attribute["key"]: attribute for attribute in snapshot["attributes"]}
    key = snapshot.get("timeout_penalty_attribute") or (snapshot["attributes"][0]["key"] if snapshot["attributes"] else "")
    amount = int(snapshot.get("timeout_penalty") or 1)
    updated = dict(values)
    if key in by_key and amount:
        updated[key] = _clamp(updated.get(key, 0) - amount, by_key[key])

    crossed = check_end_conditions(snapshot, updated)
    if crossed:
        kind, attribute_key = crossed
        return {
            "finished": True,
            "ending_kind": kind,
            "ending_key": "",
            "ending_attribute": attribute_key,
            "ending_label": by_key[attribute_key]["label"] if attribute_key in by_key else attribute_key,
            "attributes": updated,
            "path": [path_entry],
            "outcome_text": snapshot["victory_text"] if kind == "victory" else snapshot["death_text"],
            "background": snapshot["victory_background"] if kind == "victory" else snapshot["death_background"],
            "timed_out": True,
        }

    return {
        "finished": False,
        "attributes": updated,
        "path": [path_entry],
        "current": node_key,
        "timed_out": True,
    }


def take_choice(
    snapshot: dict, values: dict[str, int], node_key: str, choice_key: str
) -> dict:
    """Apply one choice. Returns the new run state (pure, no persistence)."""
    node = (snapshot.get("nodes") or {}).get(node_key)
    if node is None:
        raise AdventureError("This run points to a story node that no longer exists.")
    choice = next((c for c in node.get("choices", []) if c["key"] == choice_key), None)
    if choice is None:
        raise AdventureError("This choice is not available on the current node.")

    by_key = {attribute["key"]: attribute for attribute in snapshot["attributes"]}
    updated = dict(values)
    for attribute_key, delta in (choice.get("effects") or {}).items():
        if attribute_key not in by_key:
            continue
        updated[attribute_key] = _clamp(updated.get(attribute_key, 0) + delta, by_key[attribute_key])

    path_entry = {"node": node_key, "choice": choice_key}

    # 1. Premature death or victory.
    crossed = check_end_conditions(snapshot, updated)
    if crossed:
        kind, attribute_key = crossed
        text = snapshot["victory_text"] if kind == "victory" else snapshot["death_text"]
        background = (
            snapshot["victory_background"] if kind == "victory" else snapshot["death_background"]
        )
        label = by_key[attribute_key]["label"] if attribute_key in by_key else attribute_key
        return {
            "finished": True,
            "ending_kind": kind,
            "ending_key": "",
            "ending_attribute": attribute_key,
            "ending_label": label,
            "attributes": updated,
            "path": [path_entry],
            "outcome_text": text,
            "background": background,
        }

    # 2. Choice pointing at an ending node.
    target = choice.get("target") or ""
    if target:
        target_node = (snapshot.get("nodes") or {}).get(target)
        if target_node is None:
            raise AdventureError("This choice points to a story node that no longer exists.")
        if target_node.get("kind") == "ending":
            return {
                "finished": True,
                "ending_kind": "node",
                "ending_key": target,
                "ending_attribute": "",
                "ending_label": "",
                "attributes": updated,
                "path": [path_entry],
                "outcome_text": resolve_outcome(target_node, updated) or target_node.get("text", ""),
                "background": target_node.get("background"),
            }
        return {
            "finished": False,
            "current": target,
            "attributes": updated,
            "path": [path_entry],
        }

    # 3. Exit branch: the answer ends the story without an ending node. Such a
    #    branch has no artwork of its own, so it borrows the failure backdrop:
    #    an abrupt exit reads as a failed run, not as a neutral pause. The
    #    closing words come from the scene itself, then from the failure text —
    #    an ending screen without text is never acceptable.
    closing = node.get("text", "") or snapshot.get("death_text") or ""
    return {
        "finished": True,
        "ending_kind": "exit",
        "ending_key": "",
        "ending_attribute": "",
        "ending_label": "",
        "attributes": updated,
        "path": [path_entry],
        "outcome_text": closing,
        "background": node.get("background") or snapshot.get("death_background"),
    }
