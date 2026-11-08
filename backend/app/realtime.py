# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""In-memory WebSocket rooms for live sessions.

The documented deployment uses a single uvicorn worker: every participant of a
session therefore lands in the same process. For horizontal scaling, replace
this module with a Redis pub/sub fan-out exposing the same API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("openlearn.realtime")


class Connection:
    __slots__ = ("websocket", "role", "participant_id")

    def __init__(self, websocket: WebSocket, role: str, participant_id: int | None) -> None:
        self.websocket = websocket
        self.role = role
        self.participant_id = participant_id


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[Connection]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, code: str, websocket: WebSocket, role: str, participant_id: int | None) -> Connection:
        await websocket.accept()
        connection = Connection(websocket, role, participant_id)
        async with self._lock:
            self._rooms.setdefault(code, set()).add(connection)
        return connection

    async def disconnect(self, code: str, connection: Connection) -> None:
        async with self._lock:
            room = self._rooms.get(code)
            if room:
                room.discard(connection)
                if not room:
                    self._rooms.pop(code, None)

    def count(self, code: str) -> int:
        return len(self._rooms.get(code, ()))

    async def broadcast(self, code: str, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._rooms.get(code, ()))
        dead: list[Connection] = []
        for connection in connections:
            try:
                await connection.websocket.send_json(message)
            except Exception:  # noqa: BLE001 - a broken socket must not break the room
                dead.append(connection)
        for connection in dead:
            await self.disconnect(code, connection)

    async def send_personal(self, connection: Connection, message: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await connection.websocket.send_json(message)

    async def close_room(self, code: str) -> None:
        async with self._lock:
            connections = list(self._rooms.pop(code, ()))
        for connection in connections:
            with contextlib.suppress(Exception):
                await connection.websocket.close(code=1000)

    def rooms(self) -> list[str]:
        return sorted(self._rooms)


manager = ConnectionManager()
