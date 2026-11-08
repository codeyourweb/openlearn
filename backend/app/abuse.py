# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Temporary bans for a visitor who keeps hammering a public demo's forms.

Rate limiting alone answers each request without remembering the pattern: a
script that asks for a password reset for thirty different addresses is simply
told "slow down" thirty times, and the mail relay does the rest. This module
remembers the pattern per address and, past a threshold, stops answering at all
for a while.

Deliberately in memory: a ban is a few minutes of reprieve on a public instance,
not a durable policy, and a restart clearing them is the right failure mode.
Addresses on the operator's own networks are never banned, so a monitoring probe
or the administrator's own test cannot lock the instance for its owner.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time

from .config import settings

logger = logging.getLogger(__name__)


# Networks the operator speaks from: the bridge, the host loopback, the local
# ranges. Written out rather than `is_private`, which also covers the reserved
# documentation blocks — a real visitor is never in those, so a test address
# must still be bannable.
_NEVER_BANNED = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _allowlisted(ip: str) -> bool:
    """True when this address must never be banned."""
    if not ip:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False  # an unparsable address is the caller's problem, not a ban
    if any(address in network for network in _NEVER_BANNED if network.version == address.version):
        return True
    for entry in (settings.form_ban_allowlist or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            if entry == ip:
                return True
    return False


class BanList:
    """Strikes per address, and the bans they add up to."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._strikes: dict[str, list[float]] = {}
        self._bans: dict[str, float] = {}

    def reset(self) -> None:
        with self._lock:
            self._strikes.clear()
            self._bans.clear()

    def banned_for(self, ip: str) -> int:
        """Seconds left on this address's ban, or 0."""
        now = time.monotonic()
        with self._lock:
            until = self._bans.get(ip)
            if until is None:
                return 0
            if until <= now:
                self._bans.pop(ip, None)
                return 0
            return int(until - now) + 1

    def strike(self, ip: str) -> bool:
        """Record one rejected submission. True when this one triggered a ban."""
        if not settings.form_ban_enabled or _allowlisted(ip):
            return False
        now = time.monotonic()
        window = max(1, int(settings.form_ban_window_seconds))
        with self._lock:
            recent = [stamp for stamp in self._strikes.get(ip, []) if now - stamp < window]
            recent.append(now)
            if len(recent) < max(1, int(settings.form_ban_strikes)):
                self._strikes[ip] = recent
                return False
            self._strikes.pop(ip, None)
            self._bans[ip] = now + max(1, int(settings.form_ban_seconds))
        logger.warning("Address banned for %s s after repeated form rejections", settings.form_ban_seconds)
        return True

    def lift(self, ip: str) -> bool:
        with self._lock:
            strikes = self._strikes.pop(ip, None)
            ban = self._bans.pop(ip, None)
        return bool(strikes or ban)

    def entries(self) -> list[dict[str, object]]:
        now = time.monotonic()
        out: list[dict[str, object]] = []
        with self._lock:
            for ip, until in sorted(self._bans.items()):
                if until > now:
                    out.append({"ip": ip, "remaining_seconds": int(until - now) + 1, "strikes": 0})
            for ip, stamps in sorted(self._strikes.items()):
                recent = [stamp for stamp in stamps if now - stamp < int(settings.form_ban_window_seconds)]
                if recent:
                    out.append({"ip": ip, "remaining_seconds": 0, "strikes": len(recent)})
        return out


BANS = BanList()
