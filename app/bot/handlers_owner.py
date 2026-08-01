from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards import owner_home_keyboard
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
    if not settings.owner_chat_id:
        logger.warning(
            "OWNER_CHAT_ID not set — using chat_id=%s. Set it in .env",
            message.chat.id,
        )

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if payload.lower().startswith("c_"):
        code = payload[2:].strip()
        try:
            data = await crm.claim_setup(code)
            url = (data.get("crm_base_url") or "").rstrip("/")
            key = (data.get("api_key") or "").strip()
            if not url or not key:
                raise RuntimeError("empty claim payload")
            async with SessionLocal() as session:
                await update_setting(session, "crm_base_url", url)
                await update_setting(session, "crm_api_key", key)
            await crm.refresh_from_db()
            try:
                await crm.heartbeat(business_ok=None, version="1.0")
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat after claim failed: %s", exc)
            keys_ok = False
            groq_n = gemini_n = 0
            try:
                llm = await crm.get_llm_keys(force=True)
                groq_n = len((llm.get("groq") or {}).get("keys") or [])
                gemini_n = len((llm.get("gemini") or {}).get("keys") or [])
                keys_ok = groq_n + gemini_n > 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm after claim failed: %s", exc)
            await message.answer(
                "CRM подключена из Mini App.\n"
                f"· URL: {url}\n"
                f"· Key: {crm.masked_key()}\n"
                f"· LLM: {'OK' if keys_ok else 'EMPTY'} · Groq {groq_n} / Gemini {gemini_n}\n"
                "Дальше — Пульт или /status",
                reply_markup=owner_home_keyboard(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim failed: %s", exc)
            await message.answer(
                "Не удалось принять код из пульта (истёк или уже использован).\n"
                "Откройте Пульт → Связь → «Подключить бота» ещё раз."
            )
        return

    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
    await message.answer(
        "NST AutoReply inbox готов.\n"
        f"Режим: {cfg.get('reply_mode')} · ночь: {cfg.get('night_policy')}\n\n"
        "Управление — в пульте Mini App.\n"
        "В этот чат приходят только расшифровки голосовых и эскалации.",
        reply_markup=owner_home_keyboard(),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    if settings.owner_chat_id and message.chat.id != settings.owner_chat_id:
        return
    await message.answer(
        "Настройки переехали в пульт Mini App.",
        reply_markup=owner_home_keyboard(),
    )


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
        "· Связь: Пульт → вкладка «Связь»"
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
    await query.message.answer(
        "Настройки — в пульте Mini App.",
        reply_markup=owner_home_keyboard(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("settings:cycle:"))
async def cb_settings_cycle(query: CallbackQuery) -> None:
    await query.answer("Откройте пульт Mini App", show_alert=True)
    if query.message:
        await query.message.answer(
            "Режимы и политики — во вкладке «Режимы» пульта.",
            reply_markup=owner_home_keyboard(),
        )


@router.callback_query(F.data.in_({"settings:toggle:stt", "settings:toggle:crm_sync"}))
async def cb_settings_toggle_legacy(query: CallbackQuery) -> None:
    await query.answer("Откройте пульт Mini App", show_alert=True)
    if query.message:
        await query.message.answer(
            "Тумблеры STT / CRM — на главном экране пульта.",
            reply_markup=owner_home_keyboard(),
        )


@router.callback_query(F.data == "settings:test_card")
async def cb_test_card(query: CallbackQuery) -> None:
    from app.bot.keyboards import inbox_keyboard

    await query.message.answer(
        "Test User · Голосовое\n"
        "Расшифровка:\n"
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
