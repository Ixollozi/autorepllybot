from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards import SETTINGS_CYCLES, owner_home_keyboard, settings_keyboard
from app.bot.settings_store import get_settings_dict, update_setting
from app.config import settings
from app.crm.client import crm
from app.db.models import Dialog
from app.db.session import SessionLocal

logger = logging.getLogger("nst.autoreply.owner")
router = Router(name="owner")


def _is_owner(message: Message) -> bool:
    if not settings.owner_chat_id:
        return True  # first /start becomes owner if unset — handled below
    return message.chat.id == settings.owner_chat_id


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        await message.answer("Этот бот — служебный inbox NST AutoReply.")
        return
    # If OWNER_CHAT_ID empty, treat first starter as owner (logged)
    if not settings.owner_chat_id:
        logger.warning(
            "OWNER_CHAT_ID not set — using chat_id=%s. Set it in .env",
            message.chat.id,
        )
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
    await message.answer(
        "NST AutoReply inbox готов.\n"
        f"Режим: {cfg.get('reply_mode')} · ночь: {cfg.get('night_policy')}\n"
        "Пульт управления — Mini App. Команды: /settings /status",
        reply_markup=owner_home_keyboard(),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        return
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
    await message.answer("Настройки NST AutoReply", reply_markup=settings_keyboard(cfg))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        return
    await crm.refresh_from_db()
    keys_ok = False
    groq_n = gemini_n = 0
    try:
        data = await crm.get_llm_keys(force=True)
        groq_n = len((data.get("groq") or {}).get("keys") or [])
        gemini_n = len((data.get("gemini") or {}).get("keys") or [])
        keys_ok = groq_n + gemini_n > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("CRM keys status failed: %s", exc)
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
    await message.answer(
        "Статус:\n"
        f"· CRM URL: {crm.base or '—'}\n"
        f"· CRM key: {crm.masked_key()} · sync={'on' if cfg.get('crm_sync') else 'off'}\n"
        f"· LLM keys: {'OK' if keys_ok else 'EMPTY'} · Groq {groq_n} / Gemini {gemini_n}\n"
        f"· Режим: {cfg.get('reply_mode')} · STT: {(cfg.get('stt') or {}).get('enabled')}\n"
        "· Команды: /crm_key /crm_url /settings"
    )


@router.message(Command("crm_key"))
async def cmd_crm_key(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Использование: /crm_key ВАШ_КЛЮЧ\n"
            "Ключ берёте в CRM → Настройки → AutoReply · API-ключ → Сгенерировать."
        )
        return
    key = parts[1].strip()
    async with SessionLocal() as session:
        await update_setting(session, "crm_api_key", key)
    await crm.refresh_from_db()
    # delete message with secret if possible
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await message.answer(f"CRM API-ключ сохранён ({crm.masked_key()}). Проверка: /status")


@router.message(Command("crm_url"))
async def cmd_crm_url(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Использование: /crm_url https://crm.neosamptech.uz"
        )
        return
    url = parts[1].strip().rstrip("/")
    async with SessionLocal() as session:
        await update_setting(session, "crm_base_url", url)
    await crm.refresh_from_db()
    await message.answer(f"CRM URL сохранён: {url}")


@router.callback_query(F.data == "settings:open")
async def cb_settings_open(query: CallbackQuery) -> None:
    if settings.owner_chat_id and query.message and query.message.chat.id != settings.owner_chat_id:
        await query.answer("Нет доступа", show_alert=True)
        return
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
    await query.message.answer("Настройки", reply_markup=settings_keyboard(cfg))
    await query.answer()


@router.callback_query(F.data.startswith("settings:cycle:"))
async def cb_settings_cycle(query: CallbackQuery) -> None:
    if settings.owner_chat_id and query.message and query.message.chat.id != settings.owner_chat_id:
        await query.answer("Нет доступа", show_alert=True)
        return
    key = (query.data or "").split(":")[-1]
    values = SETTINGS_CYCLES.get(key)
    if not values:
        await query.answer("Неизвестный параметр")
        return
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
        current = cfg.get(key)
        try:
            idx = values.index(current)
        except ValueError:
            idx = -1
        new_val = values[(idx + 1) % len(values)]
        cfg = await update_setting(session, key, new_val)
    await query.message.edit_reply_markup(reply_markup=settings_keyboard(cfg))
    await query.answer(f"{key} → {new_val}")


@router.callback_query(F.data == "settings:toggle:stt")
async def cb_toggle_stt(query: CallbackQuery) -> None:
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
        stt = dict(cfg.get("stt") or {})
        stt["enabled"] = not stt.get("enabled", True)
        cfg = await update_setting(session, "stt", stt)
    await query.message.edit_reply_markup(reply_markup=settings_keyboard(cfg))
    await query.answer(f"STT → {stt['enabled']}")


@router.callback_query(F.data == "settings:toggle:crm_sync")
async def cb_toggle_crm(query: CallbackQuery) -> None:
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
        cfg = await update_setting(session, "crm_sync", not cfg.get("crm_sync", True))
    await query.message.edit_reply_markup(reply_markup=settings_keyboard(cfg))
    await query.answer(f"CRM → {cfg.get('crm_sync')}")


@router.callback_query(F.data == "settings:test_card")
async def cb_test_card(query: CallbackQuery) -> None:
    from app.bot.keyboards import inbox_keyboard

    await query.message.answer(
        "Test User · Голосовое сообщение\n"
        "Расшифровка голосового:\n"
        "«Тестовая расшифровка для проверки карточки inbox.»",
        reply_markup=inbox_keyboard(0),
    )
    await query.answer()


@router.callback_query(F.data == "settings:status")
async def cb_status(query: CallbackQuery) -> None:
    await cmd_status(query.message)
    await query.answer()


@router.callback_query(F.data.startswith("chat:pause:"))
async def cb_pause(query: CallbackQuery) -> None:
    chat_id = int((query.data or "").split(":")[-1])
    async with SessionLocal() as session:
        dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id))
        if dialog:
            dialog.paused_until = datetime.now(timezone.utc) + timedelta(hours=2)
            await session.commit()
    await query.answer("Чат на паузе 2ч")


@router.callback_query(F.data.startswith("chat:takeover:"))
async def cb_takeover(query: CallbackQuery) -> None:
    chat_id = int((query.data or "").split(":")[-1])
    async with SessionLocal() as session:
        dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id))
        if dialog:
            dialog.takeover_until = datetime.now(timezone.utc) + timedelta(hours=2)
            dialog.state = "HUMAN_TAKEOVER"
            await session.commit()
    await query.answer("Takeover включён")


@router.callback_query(F.data.startswith("chat:resume:"))
async def cb_resume(query: CallbackQuery) -> None:
    chat_id = int((query.data or "").split(":")[-1])
    async with SessionLocal() as session:
        dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id))
        if dialog:
            dialog.takeover_until = None
            dialog.paused_until = None
            if dialog.state == "HUMAN_TAKEOVER":
                dialog.state = "NURTURE"
            await session.commit()
    await query.answer("Бот снова активен")
