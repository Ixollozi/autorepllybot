"""Humanize outbound replies: context + Telegram-native style."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.brain.guards import guard_client_text
from app.brain.llm import LlmError, chat_completion
from app.config import settings

logger = logging.getLogger("nst.autoreply.humanize")

MAX_TURNS = 8

_TY_RE = re.compile(
    r"(?i)(?:^|\s)(ты|тебе|тебя|привет(?!\w)|хай|бро|брат)(?:\s|$|[!,.])"
)
_VY_RE = re.compile(
    r"(?i)(?:^|\s)(вы|вам|вас|здравствуйте|добрый\s+(день|вечер))(?:\s|$|[!,.])"
)


def _read_prompt(name: str) -> str:
    path = settings.prompts_dir / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def detect_address_form(text: str, brief: dict) -> str:
    """Return 'ty' | 'vy' | previous preference."""
    prev = (brief.get("_voice") or {}).get("address")
    t = text or ""
    has_ty = bool(_TY_RE.search(t))
    has_vy = bool(_VY_RE.search(t))
    if has_ty and not has_vy:
        return "ty"
    if has_vy and not has_ty:
        return "vy"
    return prev or "vy"


def push_turn(brief: dict, role: str, text: str) -> None:
    turns = brief.get("_turns")
    if not isinstance(turns, list):
        turns = []
    cleaned = (text or "").strip()
    if not cleaned:
        return
    turns.append({"role": role, "text": cleaned[:500]})
    brief["_turns"] = turns[-MAX_TURNS:]


def format_turns(brief: dict) -> str:
    turns = brief.get("_turns")
    if not isinstance(turns, list) or not turns:
        return "(пока коротко — начало диалога)"
    lines = []
    for t in turns[-MAX_TURNS:]:
        role = "Клиент" if t.get("role") == "user" else "Мы"
        lines.append(f"{role}: {t.get('text', '')}")
    return "\n".join(lines)


def format_brief_context(brief: dict) -> str:
    bits = []
    if brief.get("niche"):
        bits.append(f"ниша={brief['niche']}")
    if brief.get("fork"):
        bits.append(f"формат={brief['fork']}")
    if brief.get("q1"):
        bits.append(f"действие={brief['q1']}")
    if brief.get("q2"):
        bits.append(f"материалы={brief['q2']}")
    if brief.get("q3"):
        bits.append(f"разделы={brief['q3']}")
    if brief.get("client_timing_signal"):
        bits.append(f"запуск_сигнал={brief['client_timing_signal']}")
    if brief.get("client_note"):
        bits.append(f"заметка_клиента={brief['client_note']}")
    return "; ".join(bits) if bits else "бриф пустой"


def _draft_requires_fork_cta(draft: str) -> bool:
    d = draft or ""
    return ("1" in d and "2" in d) and (
        "лендинг" in d.lower() or "сайт" in d.lower() or "бот" in d.lower()
    )


def _preserves_fork_cta(text: str) -> bool:
    t = text or ""
    return "1" in t and "2" in t


async def humanize_reply(
    draft: str,
    *,
    user_text: str,
    brief: dict,
    state: str,
    identity: str,
) -> str:
    """Rewrite draft into a natural Telegram manager message. Falls back to draft."""
    draft = (draft or "").strip()
    if not draft:
        return draft

    address = detect_address_form(user_text, brief)
    voice = brief.get("_voice") if isinstance(brief.get("_voice"), dict) else {}
    voice = {**voice, "address": address}
    brief["_voice"] = voice

    system = _read_prompt("system_sales.md")
    cases = _read_prompt("cases_whitelist.md")
    identity_note = {
        "mask": "Не раскрывай, что ты ИИ/бот, если не спросят напрямую.",
        "disclose": "Можно коротко сказать, что это ассистент NST, без лекции.",
        "disclose_on_ask": "Маскируйся, пока не спросят «ты бот?».",
    }.get(identity, "")

    address_note = (
        "Обращение: на «ты»."
        if address == "ty"
        else "Обращение: на «вы»."
    )
    cta_note = ""
    if _draft_requires_fork_cta(draft):
        cta_note = (
            "КРИТИЧНО: в ответе явно оставь выбор «1» и «2» "
            "(сайт/лендинг vs бот). Без этого ответ бракованный."
        )

    messages = [
        {
            "role": "system",
            "content": f"{system}\n\nКейсы (только эти):\n{cases}\n\n{identity_note}",
        },
        {
            "role": "user",
            "content": (
                f"{address_note}\n"
                f"{cta_note}\n"
                f"Шаг воронки: {state}\n"
                f"Что уже знаем: {format_brief_context(brief)}\n\n"
                f"Недавний диалог:\n{format_turns(brief)}\n\n"
                f"Свежее сообщение клиента:\n{user_text}\n\n"
                f"Смысловой черновик (сохрани смысл и следующий шаг, "
                f"перепиши как живой менеджер в Telegram; "
                f"отреагируй на слова клиента, если там есть детали):\n{draft}\n\n"
                "Верни только текст сообщения клиенту, без кавычек и пояснений. "
                "Только кириллица и латиница — никаких иероглифов и других алфавитов."
            ),
        },
    ]
    try:
        text = await chat_completion(messages, temperature=0.65, max_tokens=450)
    except LlmError:
        logger.warning("humanize LLM failed — draft fallback")
        return draft

    text = (text or "").strip().strip("«»\"'")
    if not text:
        return draft
    ok, reason = guard_client_text(text)
    if not ok:
        logger.warning("humanize guard blocked (%s) — draft", reason)
        return draft
    if len(text) > max(len(draft) * 2.5, 900):
        logger.warning("humanize too long — draft")
        return draft
    if _draft_requires_fork_cta(draft) and not _preserves_fork_cta(text):
        logger.warning("humanize dropped fork CTA — draft")
        return draft
    return text
