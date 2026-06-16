"""Tiny JSON-backed store for per-user subscription / usage state.

Single-process polling bot, so a module-level dict + atomic file writes is
enough. State persists across restarts in bot_state.json (git-ignored).
"""
from __future__ import annotations

import json
import os
import time

STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

_data: dict[str, dict] = {}


def _load() -> None:
    global _data
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                _data = json.load(f)
        except (json.JSONDecodeError, OSError):
            _data = {}
    else:
        _data = {}


def _save() -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


_load()


def get_user(user_id: int) -> dict:
    """Return (creating if needed) the state dict for a user."""
    key = str(user_id)
    user = _data.get(key)
    if user is None:
        user = {"requests_used": 0, "subscribed_until": 0}
        _data[key] = user
        _save()
    # Backfill any missing keys for older records.
    user.setdefault("requests_used", 0)
    user.setdefault("subscribed_until", 0)
    return user


def save() -> None:
    _save()


def is_subscribed(user: dict) -> bool:
    return float(user.get("subscribed_until", 0)) > time.time()


def grant_subscription(user_id: int, days: int) -> dict:
    """Add `days` of subscription (extends if already active)."""
    user = get_user(user_id)
    now = time.time()
    base = max(now, float(user.get("subscribed_until", 0)))
    user["subscribed_until"] = base + days * 86400
    save()
    return user


def revoke_subscription(user_id: int) -> dict:
    user = get_user(user_id)
    user["subscribed_until"] = 0
    save()
    return user
