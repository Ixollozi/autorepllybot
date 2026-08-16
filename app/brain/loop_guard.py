"""Conversation loop guard: don't spam the same script on repeated «привет».

Memory lives in brief["_loop"] (SQLite dialog). We don't read Telegram history —
state + brief + last_outbound_at are the chat model.

Policy (short):
1. Explicit restart («заново», /reset) → full funnel restart + combo OK.
2. Greeting after long silence (≥ soft_restart_hours) → soft restart (deleted chat proxy).
3. Greeting / same text while already waiting for fork → short nudge, never full combo again.
4. Nudge escalation: after max nudges → hand off to manager, stop auto-spam.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

SOFT_RESTART_HOURS = 12
MAX_NUDGES_BEFORE_ESCALATE = 3

_GREETING_RE = re.compile(
    r"(?is)^\s*("
    r"привет|здравствуйте|здравствуй|добрый\s+день|добрый\s+вечер|доброе\s+утро|"
    r"hello|hi|хай|салам|assalomu\s+alaykum|ассалому\s+алейкум"
    r")[\s!.…]*$"
)

_EXPLICIT_RESTART_RE = re.compile(
    r"(?is)^\s*("
    r"заново|сначала|начать\s+сначала|reset|/reset|/start|старт|"
    r"начнём\s+сначала|начнем\s+сначала"
    r")[\s!.…]*$"
)

FORK_NUDGES = (
    "👋 Я уже тут.\n\n"
    "Напишите:\n"
    "1️⃣ — сайт / лендинг\n"
    "2️⃣ — бот\n\n"
    "Так быстрее зафиксируем формат.",
    "Кажется, крутимся на месте 🔁\n\n"
    "Нужен только выбор:\n"
    "1️⃣ — лендинг / сайт под заявки\n"
    "2️⃣ — Telegram-бот\n\n"
    "Или своими словами: что нужно сделать.",
    "Чтобы не долбить одно и то же, лучше подключу менеджера — "
    "он продолжит здесь 👤",
)


def normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[!.…?]+$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def is_greeting(text: str) -> bool:
    return bool(_GREETING_RE.match((text or "").strip()))


def is_explicit_restart(text: str) -> bool:
    return bool(_EXPLICIT_RESTART_RE.match((text or "").strip()))


def get_loop(brief: dict) -> dict[str, Any]:
    raw = brief.get("_loop")
    if isinstance(raw, dict):
        return raw
    return {}


def set_loop(brief: dict, **kwargs: Any) -> dict[str, Any]:
    loop = get_loop(brief)
    loop.update(kwargs)
    brief["_loop"] = loop
    return loop


def touch_inbound_streak(brief: dict, user_text: str) -> int:
    """Track consecutive near-identical inbound messages. Returns current streak."""
    norm = normalize_text(user_text)
    loop = get_loop(brief)
    if norm and norm == loop.get("last_norm"):
        streak = int(loop.get("streak") or 1) + 1
    else:
        streak = 1
    set_loop(brief, last_norm=norm, streak=streak)
    return streak


def mark_combo_sent(brief: dict) -> None:
    set_loop(
        brief,
        combo_sent=True,
        combo_sent_at=datetime.now(timezone.utc).isoformat(),
        last_reply_kind="combo",
    )


def mark_allow_greeting_restart(brief: dict) -> None:
    """Call when client likely wiped chat (deleted_business_messages)."""
    set_loop(brief, allow_greeting_restart=True)


def consume_allow_greeting_restart(brief: dict) -> bool:
    loop = get_loop(brief)
    if loop.get("allow_greeting_restart"):
        set_loop(brief, allow_greeting_restart=False)
        return True
    return False


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def should_soft_restart(
    *,
    brief: dict,
    last_outbound_at: datetime | None,
    now: datetime | None = None,
    soft_hours: float = SOFT_RESTART_HOURS,
) -> bool:
    """Greeting again is OK if chat was wiped or long silence after our reply."""
    if consume_allow_greeting_restart(brief):
        return True
    now = now or datetime.now(timezone.utc)
    last = _aware(last_outbound_at)
    if last is None:
        # Combo claimed in loop but no timestamp — treat as active session.
        return not bool(get_loop(brief).get("combo_sent"))
    return (now - last) >= timedelta(hours=soft_hours)


def fork_nudge(brief: dict) -> tuple[str, bool, int]:
    """Progressive nudge at WAIT_FORK. Returns (reply, escalate, nudge_count)."""
    loop = get_loop(brief)
    count = int(loop.get("nudge_count") or 0) + 1
    set_loop(brief, nudge_count=count, last_reply_kind="nudge_fork")
    idx = min(count, len(FORK_NUDGES)) - 1
    escalate = count >= MAX_NUDGES_BEFORE_ESCALATE
    return FORK_NUDGES[idx], escalate, count


def brief_question_nudge(question: str, streak: int) -> tuple[str, bool]:
    if streak <= 1:
        return (f"👋 Я на связи.\n\n{question}", False)
    if streak == 2:
        return (
            "Сообщение повторяется 🔁\n\n"
            "Ответьте коротко по сути вопроса, или напишите «менеджер».\n\n"
            f"{question}",
            False,
        )
    return (
        "Чтобы не ходить по кругу, подключаю менеджера — он продолжит здесь 👤",
        True,
    )
