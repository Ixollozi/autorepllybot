from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ContentType
from aiogram.types import BusinessConnection, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards import inbox_keyboard
from app.bot.settings_store import effective_reply_mode, get_settings_dict
from app.brain.sales import handle_sales_turn
from app.config import settings
from app.crm.client import crm
from app.db.models import (
    AnalyticsEvent,
    BusinessConnectionRow,
    Dialog,
    ProcessedMessage,
    Transcript,
    dumps_brief,
)
from app.db.session import SessionLocal
from app.stt.whisper_stt import download_and_transcribe

logger = logging.getLogger("nst.autoreply.business")
router = Router(name="business")


def _display_name(message: Message) -> str:
    user = message.from_user
    if not user:
        return "Клиент"
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or (f"@{user.username}" if user.username else str(user.id))


def _telegram_ref(message: Message) -> str:
    user = message.from_user
    if not user:
        return str(message.chat.id)
    if user.username:
        return f"@{user.username}"
    return str(user.id)


async def _log_event(session, event_type: str, chat_id: int | None, payload: dict | None = None):
    session.add(
        AnalyticsEvent(
            event_type=event_type,
            chat_id=chat_id,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
    )


async def _get_or_create_dialog(
    session,
    *,
    chat_id: int,
    business_connection_id: str | None,
    message: Message,
) -> Dialog:
    dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id))
    if dialog is None:
        dialog = Dialog(
            chat_id=chat_id,
            business_connection_id=business_connection_id,
            telegram_username=(
                f"@{message.from_user.username}"
                if message.from_user and message.from_user.username
                else None
            ),
            display_name=_display_name(message),
            state="NEW",
        )
        session.add(dialog)
        await session.flush()
    else:
        dialog.business_connection_id = business_connection_id or dialog.business_connection_id
        dialog.display_name = _display_name(message)
        if message.from_user and message.from_user.username:
            dialog.telegram_username = f"@{message.from_user.username}"
    return dialog


def _is_blocked(dialog: Dialog, now: datetime) -> bool:
    if dialog.paused_until and dialog.paused_until > now:
        return True
    if dialog.takeover_until and dialog.takeover_until > now:
        return True
    return False


async def _tempo_delay(tempo: str, bot: Bot, chat_id: int, business_connection_id: str):
    if tempo == "instant":
        delay = random.uniform(0.4, 1.0)
    elif tempo == "slow":
        delay = random.uniform(5.0, 12.0)
    else:
        delay = random.uniform(1.5, 4.0)
    try:
        await bot.send_chat_action(
            chat_id,
            ChatAction.TYPING,
            business_connection_id=business_connection_id,
        )
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(delay)


async def _send_inbox(
    bot: Bot,
    *,
    title: str,
    body: str,
    chat_id: int,
    media_file_id: str | None = None,
    media_type: str | None = None,
):
    if not settings.owner_chat_id:
        logger.warning("OWNER_CHAT_ID empty — skip inbox")
        return
    kb = inbox_keyboard(chat_id)
    if media_file_id and media_type == "voice":
        await bot.send_voice(settings.owner_chat_id, media_file_id)
    elif media_file_id and media_type == "video_note":
        await bot.send_video_note(settings.owner_chat_id, media_file_id)
    text = f"{title}\n{body}"
    await bot.send_message(settings.owner_chat_id, text[:4000], reply_markup=kb)


async def _sync_crm_events(dialog: Dialog, cfg: dict, events: list[dict], message: Message):
    if not cfg.get("crm_sync", True) or not crm.enabled:
        return
    try:
        if not dialog.crm_lead_id:
            lead = await crm.upsert(
                {
                    "telegram": _telegram_ref(message),
                    "contact_name": dialog.display_name,
                    "niche": dialog.niche,
                }
            )
            dialog.crm_lead_id = lead["id"]
        for ev in events:
            ext = (
                f"tg:{dialog.chat_id}:{message.message_id}:{ev.get('type')}"
            )
            await crm.post_event(
                dialog.crm_lead_id,
                external_event_id=ext,
                event_type=ev.get("type") or "event",
                note=ev.get("note"),
                patch=ev.get("patch"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("CRM sync failed: %s", exc)


@router.business_connection()
async def on_business_connection(event: BusinessConnection, bot: Bot) -> None:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(BusinessConnectionRow).where(
                BusinessConnectionRow.connection_id == event.id
            )
        )
        can_reply = True
    rights = getattr(event, "rights", None)
    if rights is not None:
        can_reply = bool(getattr(rights, "can_reply", True))
    elif hasattr(event, "can_reply"):
        can_reply = bool(event.can_reply)
        if row is None:
            row = BusinessConnectionRow(
                connection_id=event.id,
                user_id=event.user.id,
                user_chat_id=event.user_chat_id,
                can_reply=can_reply,
                is_enabled=event.is_enabled,
            )
            session.add(row)
        else:
            row.can_reply = can_reply
            row.is_enabled = event.is_enabled
            row.user_chat_id = event.user_chat_id
        await session.commit()
    if settings.owner_chat_id:
        status = "OK" if event.is_enabled and can_reply else "WARN"
        await bot.send_message(
            settings.owner_chat_id,
            f"Business connection {status}\n"
            f"id={event.id}\ncan_reply={can_reply}\nenabled={event.is_enabled}",
        )


@router.business_message()
async def on_business_message(message: Message, bot: Bot) -> None:
    # Outgoing from bot itself — ignore
    if message.sender_business_bot is not None:
        return

    biz_id = message.business_connection_id
    if not biz_id:
        return

    chat_id = message.chat.id
    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        # Dedupe
        try:
            session.add(
                ProcessedMessage(
                    business_connection_id=biz_id,
                    message_id=message.message_id,
                )
            )
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return

        cfg = await get_settings_dict(session)
        ignore = set(cfg.get("ignore_list") or [])
        if str(chat_id) in ignore or (
            message.from_user
            and message.from_user.username
            and f"@{message.from_user.username}" in ignore
        ):
            await session.commit()
            return

        dialog = await _get_or_create_dialog(
            session,
            chat_id=chat_id,
            business_connection_id=biz_id,
            message=message,
        )
        dialog.last_inbound_at = now

        # Owner replied from phone: message.from_user is business account owner
        # Detect: if from_user.id matches connection user — takeover
        conn = await session.scalar(
            select(BusinessConnectionRow).where(
                BusinessConnectionRow.connection_id == biz_id
            )
        )
        if (
            conn
            and message.from_user
            and message.from_user.id == conn.user_id
        ):
            dialog.takeover_until = now + timedelta(hours=2)
            dialog.state = "HUMAN_TAKEOVER"
            await _log_event(session, "takeover", chat_id, {"reason": "owner_outbound"})
            await session.commit()
            if settings.owner_chat_id:
                await bot.send_message(
                    settings.owner_chat_id,
                    f"Takeover: вы ответили вручную в чате {_display_name(message)}",
                )
            return

        stt_cfg = cfg.get("stt") or {}
        user_text = (message.text or message.caption or "").strip()
        media_file_id = None
        media_type = None
        transcript = None

        if message.content_type == ContentType.VOICE and stt_cfg.get("enabled", True) and stt_cfg.get("voice", True):
            media_file_id = message.voice.file_id
            media_type = "voice"
            try:
                transcript, lang = await download_and_transcribe(
                    bot, message.voice.file_id, language="ru"
                )
                user_text = transcript or user_text
                session.add(
                    Transcript(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=transcript or "",
                        lang=lang,
                    )
                )
                await _log_event(session, "stt_ok", chat_id, {"len": len(transcript or "")})
            except Exception as exc:  # noqa: BLE001
                logger.exception("STT failed: %s", exc)
                transcript = None
                await _log_event(session, "stt_fail", chat_id, {"error": str(exc)})

        elif (
            message.content_type == ContentType.VIDEO_NOTE
            and stt_cfg.get("enabled", True)
            and stt_cfg.get("video_note", True)
        ):
            media_file_id = message.video_note.file_id
            media_type = "video_note"
            try:
                transcript, lang = await download_and_transcribe(
                    bot, message.video_note.file_id, language="ru"
                )
                user_text = transcript or user_text
                session.add(
                    Transcript(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=transcript or "",
                        lang=lang,
                    )
                )
                await _log_event(session, "stt_ok", chat_id, {})
            except Exception as exc:  # noqa: BLE001
                logger.exception("STT video_note failed: %s", exc)
                await _log_event(session, "stt_fail", chat_id, {"error": str(exc)})

        await _log_event(session, "msg_in", chat_id, {"type": message.content_type})

        # Inbox card
        name = _display_name(message)
        if media_type == "voice":
            title = f"{name} · Голосовое сообщение"
            body = (
                f"Расшифровка голосового:\n«{transcript}»"
                if transcript
                else "Не удалось расшифровать — оригинал выше."
            )
        elif media_type == "video_note":
            title = f"{name} · Видеосообщение"
            body = (
                f"Расшифровка:\n«{transcript}»"
                if transcript
                else "Не удалось расшифровать — оригинал выше."
            )
        else:
            title = f"{name} · Сообщение"
            body = user_text or f"({message.content_type})"

        try:
            await _send_inbox(
                bot,
                title=title,
                body=body,
                chat_id=chat_id,
                media_file_id=media_file_id,
                media_type=media_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Inbox send failed: %s", exc)

        if _is_blocked(dialog, now):
            await session.commit()
            return

        mode = effective_reply_mode(cfg, now)
        if dialog.state == "HUMAN_TAKEOVER" and dialog.takeover_until and dialog.takeover_until > now:
            mode = "TAKEOVER"

        if not user_text and not transcript:
            await session.commit()
            return

        result = await handle_sales_turn(
            user_text=user_text,
            state=dialog.state,
            brief_raw=dialog.brief_json,
            settings=cfg,
            mode=mode,
            niche_hint=dialog.niche,
        )

        dialog.state = result.new_state
        dialog.brief_json = dumps_brief(result.brief)
        if result.brief.get("niche"):
            dialog.niche = result.brief["niche"]

        await _sync_crm_events(dialog, cfg, result.crm_events, message)

        # Persist qualification into CRM
        if (
            cfg.get("crm_sync", True)
            and crm.enabled
            and dialog.crm_lead_id
            and result.brief
        ):
            try:
                await crm.patch(
                    dialog.crm_lead_id,
                    {"qualification_json": dumps_brief(result.brief)},
                )
                if result.brief.get("client_timing_signal"):
                    await crm.add_note(
                        dialog.crm_lead_id,
                        f"Желаемый запуск (сигнал): {result.brief['client_timing_signal']}",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("CRM patch brief failed: %s", exc)

        if result.escalate and settings.owner_chat_id:
            await bot.send_message(
                settings.owner_chat_id,
                f"Нужен человек\n"
                f"{name} · {result.escalate_reason}\n"
                f"Стадия: {result.new_state}\n"
                f"Кратко: {(user_text or '')[:200]}",
                reply_markup=inbox_keyboard(chat_id),
            )
            await _log_event(
                session, "escalation", chat_id, {"reason": result.escalate_reason}
            )

        reply = result.reply
        if reply and not result.assist_only and mode not in ("MANUAL", "SILENT", "TAKEOVER", "ASSIST"):
            limits = cfg.get("limits") or {}
            max_chars = int(limits.get("max_chars") or 900)
            reply = reply[:max_chars]
            await _tempo_delay(cfg.get("tempo") or "human", bot, chat_id, biz_id)
            await bot.send_message(
                chat_id,
                reply,
                business_connection_id=biz_id,
            )
            dialog.last_outbound_at = datetime.now(timezone.utc)
            await _log_event(session, "msg_out", chat_id, {"state": result.new_state})
        elif reply and (result.assist_only or mode == "ASSIST"):
            if settings.owner_chat_id:
                await bot.send_message(
                    settings.owner_chat_id,
                    f"Черновик для {name}:\n\n{reply}",
                    reply_markup=inbox_keyboard(chat_id),
                )

        await _log_event(
            session,
            "state_transition",
            chat_id,
            {"to": result.new_state},
        )
        await session.commit()
