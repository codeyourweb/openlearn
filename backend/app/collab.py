# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Live editing of wiki pages: one room per page, one merged text per change.

The server is the single ordering point, and it never trusts a client's idea of
what the document looks like. A browser sends the text it holds plus the
revision it started from; the server merges that text with what everybody else
wrote since (three-way merge against the snapshot of that revision), then
broadcasts the result as one minimal splice. Every screen applies the same
splices in the same order, so all screens agree — convergence does not depend on
getting an operational-transform algebra right, only on the server's order.

Merging happens line by line, then character by character inside a conflicting
paragraph, so two people typing in different sentences of the same paragraph
keep both sentences instead of one of them winning.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import json
import logging
import re

from fastapi import WebSocket

logger = logging.getLogger("openlearn.collab")

#: Returned when a client's text already matches the room: nothing to merge and
#: nothing to resync, so the socket stays silent instead of pushing a full copy.
NO_CHANGE = "no-change"

MAX_DOCUMENT_BYTES = 400_000
MAX_HISTORY = 120  # revisions kept so a late client can still be merged
PERSIST_DELAY = 1.2  # seconds of quiet before the live text reaches SQLite
CHAR_MERGE_LIMIT = 4_000  # above this, a conflicting region stays at line level

PALETTE = (
    "#3b82f6",
    "#ef4444",
    "#10b981",
    "#f59e0b",
    "#8b5cf6",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
)


def color_for(user_id: int, name: str = "") -> str:
    seed = f"{user_id}:{name}".encode()
    index = int(hashlib.sha256(seed).hexdigest()[:6], 16) % len(PALETTE)
    return PALETTE[index]


# ---------------------------------------------------------------------------
# Three-way merge
# ---------------------------------------------------------------------------
def _chunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    """Regions of ``base`` that ``other`` changed, as (start, end, replacement)."""
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    changes: list[tuple[int, int, list[str]]] = []
    for tag, start, end, other_start, other_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append((start, end, other[other_start:other_end]))
    return changes


def _apply_region(base: list[str], changes: list[tuple[int, int, list[str]]], start: int, end: int):
    """Apply the changes falling inside [start, end) to that slice of base."""
    out: list[str] = []
    cursor = start
    for change_start, change_end, replacement in changes:
        if change_start > cursor:
            out.extend(base[cursor:change_start])
        out.extend(replacement)
        cursor = max(cursor, change_end)
    out.extend(base[cursor:end])
    return out


def merge_units(base: list[str], mine: list[str], theirs: list[str]) -> tuple[list[str], bool]:
    """Merge two edits of ``base``; returns (merged, conflicted)."""
    if mine == theirs or theirs == base:
        return mine, False
    if mine == base:
        return theirs, False

    changes_a = _chunks(base, mine)
    changes_b = _chunks(base, theirs)
    merged: list[str] = []
    cursor = 0
    index_a = index_b = 0
    conflicted = False

    while index_a < len(changes_a) or index_b < len(changes_b):
        starts = []
        if index_a < len(changes_a):
            starts.append(changes_a[index_a][0])
        if index_b < len(changes_b):
            starts.append(changes_b[index_b][0])
        start = min(starts)
        if start > cursor:
            merged.extend(base[cursor:start])
            cursor = max(cursor, start)

        # Gather every change from either side that overlaps the current region.
        end = cursor
        group_a: list[tuple[int, int, list[str]]] = []
        group_b: list[tuple[int, int, list[str]]] = []
        while True:
            progressed = False
            if index_a < len(changes_a) and changes_a[index_a][0] <= end:
                change = changes_a[index_a]
                group_a.append(change)
                end = max(end, change[1])
                index_a += 1
                progressed = True
            if index_b < len(changes_b) and changes_b[index_b][0] <= end:
                change = changes_b[index_b]
                group_b.append(change)
                end = max(end, change[1])
                index_b += 1
                progressed = True
            if not progressed:
                break

        region = base[cursor:end]
        mine_region = _apply_region(base, group_a, cursor, end)
        theirs_region = _apply_region(base, group_b, cursor, end)
        if mine_region == theirs_region:
            merged.extend(mine_region)
        elif mine_region == region:
            merged.extend(theirs_region)
        elif theirs_region == region:
            merged.extend(mine_region)
        else:
            # Both rewrote the same passage differently. The live text already on
            # the server wins — the author is told and can redo their change —
            # because duplicating the passage would corrupt the page silently.
            conflicted = True
            merged.extend(theirs_region)
        cursor = end

    if cursor < len(base):
        merged.extend(base[cursor:])
    return merged, conflicted


def _words(text: str) -> list[tuple[int, int]]:
    """Character spans of the words of a text, so a merge can tell them apart."""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\S+", text):
        spans.append((match.start(), match.end()))
    return spans


def _touched_words(text: str, changes: list[tuple[int, int, str]]) -> set[int]:
    spans = _words(text)
    touched: set[int] = set()
    for start, end, _replacement in changes:
        # An insertion touches the word it lands inside, or the word before it.
        probe_start, probe_end = start, max(end, start + 1)
        for index, (word_start, word_end) in enumerate(spans):
            if word_start < probe_end and word_end > probe_start:
                touched.add(index)
    return touched


def merge_text(base: str, mine: str, theirs: str) -> tuple[str, bool]:
    """Three-way merge of two texts written on top of ``base``."""
    if mine == theirs or theirs == base:
        return mine, False
    if mine == base:
        return theirs, False

    merged, conflicted = merge_units(base.splitlines(keepends=True), mine.splitlines(keepends=True), theirs.splitlines(keepends=True))
    text = "".join(merged)
    if not conflicted:
        return text, False

    # The lines disagreed, but the people may only have touched different words
    # of the same line: retry character by character on that region.
    if len(base) <= CHAR_MERGE_LIMIT:
        # Down to characters, two edits of the same line usually do not overlap.
        # They must not touch the same word though: merging "53" into "5353"
        # and "1053" would invent a number nobody typed.
        both_words = _touched_words(base, _chunks(list(base), list(mine)))
        their_words = _touched_words(base, _chunks(list(base), list(theirs)))
        if both_words & their_words:
            return theirs, True
        careful, still_conflicted = merge_units(list(base), list(mine), list(theirs))
        careful_text = "".join(careful)
        return careful_text, still_conflicted
    return text, True


def minimal_splice(before: str, after: str) -> tuple[int, int, str]:
    """The smallest (pos, delete, insert) turning ``before`` into ``after``."""
    start = 0
    limit = min(len(before), len(after))
    while start < limit and before[start] == after[start]:
        start += 1
    end_before, end_after = len(before), len(after)
    while end_before > start and end_after > start and before[end_before - 1] == after[end_after - 1]:
        end_before -= 1
        end_after -= 1
    return start, end_before - start, after[start:end_after]


def apply_splice(text: str, pos: int, delete: int, insert: str) -> str:
    return text[:pos] + insert + text[pos + delete :]


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
class Client:
    __slots__ = ("client_id", "user_id", "name", "color", "can_write", "websocket", "anchor", "head")

    def __init__(
        self,
        client_id: str,
        user_id: int,
        name: str,
        color: str,
        can_write: bool,
        websocket: WebSocket | None = None,
    ) -> None:
        self.client_id = client_id
        self.user_id = user_id
        self.name = name
        self.color = color
        self.can_write = can_write
        self.websocket = websocket
        self.anchor = 0
        self.head = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "user_id": self.user_id,
            "name": self.name,
            "color": self.color,
            "can_write": self.can_write,
            "anchor": self.anchor,
            "head": self.head,
        }


class CollabRoom:
    def __init__(self, page_id: int, content: str) -> None:
        self.page_id = page_id
        self.content = content
        self.rev = 0
        self.clients: dict[str, Client] = {}
        self._snapshots: dict[int, str] = {0: content}
        self._task: asyncio.Task | None = None
        self.last_author_id: int | None = None

    # -- editing ---------------------------------------------------------
    def apply_text(
        self, base_rev: int, text: str
    ) -> tuple[int, int, int, str, bool] | None | str:
        """Merge a client's text; returns (rev, pos, delete, insert, conflict).

        `None` asks the client for a resync; `NO_CHANGE` means the room already
        holds that text and the client needs no answer at all.
        """
        if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            return None
        if base_rev > self.rev:
            return None
        if text == self.content:
            return NO_CHANGE
        if base_rev == self.rev:
            merged, conflicted = text, False
        else:
            base = self._snapshots.get(base_rev)
            if base is None:
                return None
            merged, conflicted = merge_text(base, text, self.content)

        pos, delete, insert = minimal_splice(self.content, merged)
        if not delete and not insert:
            return NO_CHANGE
        self.content = merged
        self.rev += 1
        self._snapshots[self.rev] = merged
        if len(self._snapshots) > MAX_HISTORY:
            for stale in sorted(self._snapshots)[:-MAX_HISTORY]:
                self._snapshots.pop(stale, None)
        self.schedule_persist()
        return self.rev, pos, delete, insert, conflicted

    def reset(self, content: str) -> int:
        """Adopt an authoritative text (explicit save, restore, import)."""
        self.content = content
        self.rev += 1
        self._snapshots = {self.rev: content}
        return self.rev

    # -- persistence -----------------------------------------------------
    def note_author(self, author_id: int | None) -> None:
        """Remember who typed last: the draft records it, the page does not."""
        if author_id:
            self.last_author_id = author_id

    def schedule_persist(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # synchronous context (tests, CLI)
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = loop.create_task(self._persist_later())

    async def _persist_later(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(PERSIST_DELAY)
            snapshot = self.content
            persist = _persist
            if persist is None:
                return
            try:
                await asyncio.to_thread(persist, self.page_id, snapshot, self.last_author_id)
            except Exception:  # noqa: BLE001 - a lost autosave must not kill the room
                logger.exception("Live autosave failed for page %s", self.page_id)

    # -- presence --------------------------------------------------------
    def users(self) -> list[dict[str, object]]:
        return [client.as_dict() for client in self.clients.values()]

    async def broadcast(self, message: dict[str, object], *, skip: str | None = None) -> None:
        payload = json.dumps(message, ensure_ascii=False)
        dead: list[str] = []
        for client_id, client in list(self.clients.items()):
            if client_id == skip or client.websocket is None:
                continue
            try:
                await client.websocket.send_text(payload)
            except Exception:  # noqa: BLE001 - one dead socket must not stop the room
                dead.append(client_id)
        for client_id in dead:
            self.clients.pop(client_id, None)


_persist = None
_rooms: dict[int, CollabRoom] = {}
_loop: asyncio.AbstractEventLoop | None = None


def configure_persist(callback) -> None:
    """Register the function that writes live text back to SQLite."""
    global _persist
    _persist = callback


def bind_loop() -> None:
    """Remember the serving loop so synchronous routes can reach the rooms."""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None


def room_for(page_id: int, content: str) -> CollabRoom:
    room = _rooms.get(page_id)
    if room is None:
        room = CollabRoom(page_id=page_id, content=content)
        _rooms[page_id] = room
    return room


def peek(page_id: int) -> CollabRoom | None:
    return _rooms.get(page_id)


def drop(page_id: int) -> None:
    room = _rooms.pop(page_id, None)
    if room is not None and room._task is not None:
        room._task.cancel()


def reset_all() -> None:
    """Forget every room and cancel pending autosaves (tests, shutdown).

    A room keeps a task sleeping until the typing stops; if that task outlives
    the database it was opened on, its write lands in an unrelated test run and
    locks the file. Dropping the rooms is the only safe teardown.
    """
    for room in list(_rooms.values()):
        if room._task is not None:
            with contextlib.suppress(RuntimeError):
                room._task.cancel()
    _rooms.clear()


def reset_room(page_id: int, content: str) -> None:
    room = _rooms.get(page_id)
    if room is None:
        return
    rev = room.reset(content)
    _broadcast_soon(room, {"type": "reset", "rev": rev, "content": content})


def _broadcast_soon(room: CollabRoom, message: dict[str, object]) -> None:
    """Broadcast from a synchronous route without blocking it."""
    loop = _loop
    if loop is None or loop.is_closed():
        return

    def schedule() -> None:
        loop.create_task(room.broadcast(message))

    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(schedule)


def editors_on(page_id: int) -> int:
    room = _rooms.get(page_id)
    return len(room.clients) if room else 0
