"""Human-readable Russian labels for operator inbox / Mini App."""

from __future__ import annotations

STAGE_RU: dict[str, str] = {
    "NEW": "Новый диалог",
    "GREETING_QUALIFY": "Приветствие",
    "MSG1_COMBO_SENT": "Отправили первый блок",
    "WAIT_FORK": "Ждём: сайт или бот",
    "BRIEF_Q1": "Уточняем задачу",
    "BRIEF_Q2": "Уточняем материалы",
    "BRIEF_Q3": "Уточняем разделы",
    "BRIEF_Q4": "Уточняем сроки",
    "TZ_DRAFT_SENT": "Отправили резюме",
    "WAIT_TZ_CONFIRM": "Ждём подтверждение резюме",
    "NURTURE": "Мягкий follow-up",
    "HUMAN_TAKEOVER": "Ведёт менеджер",
    "TAKEOVER": "Ведёт менеджер",
    "ACTIVE": "Бот ведёт диалог",
    "CLOSED": "Закрыт",
    "DONE": "Готово",
    "LOST": "Потерян",
}

REASON_RU: dict[str, str] = {
    "hostile": "Грубость / отказ — бот остановился",
    "loop_stuck_at_fork": "Клиент застрял на выборе формата",
    "owner_outbound": "Вы ответили вручную — бот замолчал",
    "caught_or_bot_ask": "Спросил, бот ли это",
    "client_asked_manager": "Попросил менеджера",
    "offtopic": "Ушёл не по теме",
    "sales_depth_ack": "Режим «только принять»",
    "sales_depth_combo": "Остановились после выбора формата",
    "tz_confirmed": "Резюме подтверждено — нужен менеджер",
    "need_human": "Нужен человек",
    "owner_outbound": "Вы ответили вручную",
}

MODE_RU: dict[str, str] = {
    "AUTO": "отвечает сам",
    "ASSIST": "черновики вам",
    "MANUAL": "ручной режим",
    "ACK_ONLY": "ночью только «принято»",
    "SILENT": "ночью молчит",
}

NIGHT_RU: dict[str, str] = {
    "full_auto": "ночью тоже отвечает",
    "ack_only": "ночью только «принято»",
    "silent": "ночью молчит",
    "assist_night": "ночью черновики вам",
}


def stage_ru(state: str | None) -> str:
    key = (state or "").strip()
    return STAGE_RU.get(key, key or "—")


def reason_ru(reason: str | None) -> str:
    key = (reason or "").strip()
    return REASON_RU.get(key, key or "Нужен человек")


def mode_ru(mode: str | None) -> str:
    key = (mode or "").strip()
    return MODE_RU.get(key, key or "—")


def night_ru(policy: str | None) -> str:
    key = (policy or "").strip()
    return NIGHT_RU.get(key, key or "—")


def stt_provider_ru(provider: str | None) -> str:
    p = (provider or "").lower()
    if p == "groq":
        return "облако"
    if p in ("local", "whisper", "faster-whisper"):
        return "на устройстве"
    return provider or "—"
