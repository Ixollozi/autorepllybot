"""Timezone-safe datetime helpers (SQLite often returns naive UTC)."""

from __future__ import annotations

from datetime import datetime, timezone


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_future(dt: datetime | None, *, relative_to: datetime | None = None) -> bool:
    a = aware(dt)
    if a is None:
        return False
    ref = aware(relative_to) or now_utc()
    return a > ref
