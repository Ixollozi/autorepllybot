from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ContentType
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards import inbox_keyboard
from app.bot.settings_store import (
    apply_crm_settings,
    apply_pending_dialog_actions,
    effective_reply_mode,
    get_settings_dict,
)
from app.brain.guards import guard_client_text
from app.brain.loop_guard import mark_allow_greeting_restart
from app.brain.sales import (
    brief_for_crm_json,
    brief_to_crm_patch,
    handle_sales_turn,
    script_fields_for_crm,
)
from app.config import settings
from app.crm.client import crm
from app.db.models import (
    AnalyticsEvent,
    BusinessConnectionRow,
    Dialog,
    ProcessedMessage,
    Transcript,
    dumps_brief,
    loads_brief,
)
from app.db.session import SessionLocal
from app.stt.whisper_stt import download_and_transcribe_rich

logger = logging.getLogger("nst.autoreply.business")
router = Router(name="business")


async def _sync_miniapp_actions(session) -> None:
    """Pull Mini App takeover/resume before deciding whether to reply."""
    if not crm.enabled:
        return
    try:
        remote = await crm.get_settings()
        if not remote:
            return
        await apply_crm_settings(session, remote)
        applied = await apply_pending_dialog_actions(session, remote)
        if applied:
            await crm.ack_dialog_actions(applied)
            logger.info("Synced %d Mini App dialog actions on inbound", len(applied))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mini App action sync failed: %s", exc)


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


async def _push_dialog_to_crm(dialog: Dialog) -> None:
    if not crm.enabled:
        logger.warning(
            "Skip dialog sync chat=%s — CRM not connected (Mini App → Связь → Подключить бота)",
            dialog.chat_id,
        )
        return
    try:
        await crm.upsert_dialog(
            {
                "chat_id": dialog.chat_id,
                "business_connection_id": dialog.business_connection_id,
                "telegram_username": dialog.telegram_username,
                "display_name": dialog.display_name,
                "state": dialog.state,
                "brief_json": dialog.brief_json,
                "crm_lead_id": dialog.crm_lead_id,
                "takeover_until": (
                    dialog.takeover_until.isoformat() if dialog.takeover_until else None
                ),
                "paused_until": (
                    dialog.paused_until.isoformat() if dialog.paused_until else None
                ),
                "language": dialog.language,
                "niche": dialog.niche,
                "last_inbound_at": (
                    dialog.last_inbound_at.isoformat() if dialog.last_inbound_at else None
                ),
                "last_outbound_at": (
                    dialog.last_outbound_at.isoformat()
                    if dialog.last_outbound_at
                    else None
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("CRM dialog upsert failed chat=%s: %s", dialog.chat_id, exc)


async def _push_message(
    chat_id: int,
    role: str,
    text: str,
    *,
    tg_message_id: int | None = None,
) -> None:
    if not (text or "").strip():
        return
    try:
        await crm.append_message(
            chat_id=chat_id,
            role=role,
            text=text.strip(),
            tg_message_id=tg_message_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("CRM message append failed chat=%s: %s", chat_id, exc)


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
    from app.bot.timeutil import aware, is_future

    now = aware(now) or now
    if is_future(dialog.paused_until, relative_to=now):
        return True
    if is_future(dialog.takeover_until, relative_to=now):
        return True
    return False


def _bot_active_for_inbox(dialog: Dialog | None, now: datetime | None = None) -> bool:
    """True = bot replies to client; False = human takeover/pause."""
    from app.bot.timeutil import aware, is_future, now_utc

    if dialog is None:
        return True
    now = aware(now) or now_utc()
    if is_future(dialog.takeover_until, relative_to=now):
        return False
    if is_future(dialog.paused_until, relative_to=now):
        return False
    # HUMAN_TAKEOVER without active takeover window = stale; treat as bot-active
    # only when window still open (set on escalate + takeover button).
    if dialog.state == "HUMAN_TAKEOVER" and is_future(dialog.takeover_until, relative_to=now):
        return False
    return True


def _clear_expired_takeover(dialog: Dialog, now: datetime) -> None:
    """Unstick dialogs left in HUMAN_TAKEOVER after window expired."""
    from app.bot.timeutil import aware, is_future

    now = aware(now) or now
    takeover = aware(dialog.takeover_until)
    if dialog.state == "HUMAN_TAKEOVER":
        if takeover is None or not is_future(takeover, relative_to=now):
            dialog.takeover_until = None
            dialog.state = "WAIT_FORK"
    elif takeover is not None and not is_future(takeover, relative_to=now):
        dialog.takeover_until = None


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
    kb = inbox_keyboard(chat_id, bot_active=True)
    if media_file_id and media_type == "voice":
        await bot.send_voice(settings.owner_chat_id, media_file_id)
    elif media_file_id and media_type == "video_note":
        await bot.send_video_note(settings.owner_chat_id, media_file_id)
    text = f"{title}\n\n{body}"
    await bot.send_message(settings.owner_chat_id, text[:4000], reply_markup=kb)


async def _sync_crm_events(dialog: Dialog, cfg: dict, events: list[dict], message: Message):
    if not cfg.get("crm_sync", True) or not crm.enabled:
        return
    try:
        depth = cfg.get("sales_depth") or "full_tz"
        brief = loads_brief(dialog.brief_json)
        if not dialog.crm_lead_id:
            upsert_body = {
                "telegram": _telegram_ref(message),
                "contact_name": dialog.display_name,
                "niche": dialog.niche or brief.get("niche"),
                "status": "Написал",
                **script_fields_for_crm(brief, sales_depth=depth, stage="upsert"),
            }
            lead = await crm.upsert(upsert_body)
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


@router.deleted_business_messages()
async def on_deleted_business_messages(event: BusinessMessagesDeleted) -> None:
    """Client wiped chat history → next «привет» may restart greeting once."""
    chat_id = event.chat.id if event.chat else None
    if chat_id is None:
        return
    ids = list(event.message_ids or [])
    if len(ids) < 2:
        # Single delete is not a wipe; ignore.
        return
    async with SessionLocal() as session:
        dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id))
        if not dialog:
            return
        brief = loads_brief(dialog.brief_json)
        mark_allow_greeting_restart(brief)
        dialog.brief_json = dumps_brief(brief)
        await session.commit()
        logger.info(
            "Chat wipe signal chat=%s deleted=%s → allow greeting restart",
            chat_id,
            len(ids),
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

        await _sync_miniapp_actions(session)

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
        _clear_expired_takeover(dialog, now)

        # Human (business owner) wrote in this chat → bot stays silent
        from app.bot.timeutil import is_future

        conn = await session.scalar(
            select(BusinessConnectionRow).where(
                BusinessConnectionRow.connection_id == biz_id
            )
        )
        from_id = message.from_user.id if message.from_user else None
        chat_peer = message.chat.id if message.chat else None
        owner_by_conn = bool(conn and from_id and from_id == conn.user_id)
        owner_by_env = bool(
            from_id and settings.owner_chat_id and from_id == settings.owner_chat_id
        )
        # Private Business chat: client inbound → from_user.id == chat.id;
        # owner outbound → from_user is owner, chat.id is client.
        owner_by_peer = bool(from_id and chat_peer and from_id != chat_peer)
        if owner_by_conn or owner_by_env or owner_by_peer:
            already = dialog.state == "HUMAN_TAKEOVER" and is_future(
                dialog.takeover_until, relative_to=now
            )
            dialog.takeover_until = now + timedelta(hours=4)
            dialog.state = "HUMAN_TAKEOVER"
            await _log_event(
                session,
                "takeover",
                chat_id,
                {
                    "reason": "owner_outbound",
                    "via": (
                        "conn"
                        if owner_by_conn
                        else ("owner_chat" if owner_by_env else "peer_mismatch")
                    ),
                },
            )
            await session.commit()
            await _push_dialog_to_crm(dialog)
            out_text = (message.text or message.caption or "").strip()
            if out_text:
                await _push_message(chat_id, "out", f"[вы] {out_text[:2000]}")
            if not already and settings.owner_chat_id:
                from app.bot.labels import stage_ru

                await bot.send_message(
                    settings.owner_chat_id,
                    (
                        "👤 Вы в диалоге — бот замолчал\n\n"
                        f"Клиент: {_display_name(message)}\n"
                        f"Сейчас: {stage_ru('HUMAN_TAKEOVER')}"
                    ),
                    reply_markup=inbox_keyboard(chat_id, bot_active=False),
                )
            return

        dialog.last_inbound_at = now

        stt_cfg = cfg.get("stt") or {}
        user_text = (message.text or message.caption or "").strip()
        media_file_id = None
        media_type = None
        transcript = None
        stt_meta = None

        if message.content_type == ContentType.VOICE and stt_cfg.get("enabled", True) and stt_cfg.get("voice", True):
            media_file_id = message.voice.file_id
            media_type = "voice"
            try:
                stt_meta = await download_and_transcribe_rich(
                    bot, message.voice.file_id, language="ru"
                )
                transcript = stt_meta.text or None
                user_text = transcript or user_text
                session.add(
                    Transcript(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=transcript or "",
                        lang=stt_meta.language,
                    )
                )
                await _log_event(
                    session,
                    "stt_ok",
                    chat_id,
                    {
                        "len": len(transcript or ""),
                        "provider": stt_meta.provider,
                        "logprob": stt_meta.avg_logprob,
                        "low_confidence": stt_meta.low_confidence,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("STT failed: %s", exc)
                transcript = None
                stt_meta = None
                await _log_event(session, "stt_fail", chat_id, {"error": str(exc)})

        elif (
            message.content_type == ContentType.VIDEO_NOTE
            and stt_cfg.get("enabled", True)
            and stt_cfg.get("video_note", True)
        ):
            media_file_id = message.video_note.file_id
            media_type = "video_note"
            try:
                stt_meta = await download_and_transcribe_rich(
                    bot, message.video_note.file_id, language="ru"
                )
                transcript = stt_meta.text or None
                user_text = transcript or user_text
                session.add(
                    Transcript(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=transcript or "",
                        lang=stt_meta.language,
                    )
                )
                await _log_event(
                    session,
                    "stt_ok",
                    chat_id,
                    {
                        "provider": stt_meta.provider,
                        "logprob": stt_meta.avg_logprob,
                        "low_confidence": stt_meta.low_confidence,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("STT video_note failed: %s", exc)
                stt_meta = None
                await _log_event(session, "stt_fail", chat_id, {"error": str(exc)})

        await _log_event(session, "msg_in", chat_id, {"type": message.content_type})

        name = _display_name(message)
        inbound_text = user_text or (
            f"[голос] {transcript}" if transcript and media_type == "voice" else ""
        ) or (
            f"[кружок] {transcript}" if transcript and media_type == "video_note" else ""
        ) or f"({message.content_type})"

        # Owner inbox: ONLY voice / video-note transcriptions (not every text)
        if media_type in ("voice", "video_note"):
            from app.bot.labels import stt_provider_ru

            kind = "голосовое" if media_type == "voice" else "видеосообщение"
            conf_note = ""
            if stt_meta is not None:
                conf_note = f"\n\nРаспознавание: {stt_provider_ru(stt_meta.provider)}"
                if stt_meta.low_confidence:
                    conf_note += "\n⚠️ Низкая уверенность — лучше переслушать"
            body = (
                f"Расшифровка:\n«{transcript}»{conf_note}"
                if transcript
                else f"Не удалось расшифровать — оригинал выше.{conf_note}"
            )
            try:
                await _send_inbox(
                    bot,
                    title=f"🎤 {name} · {kind}",
                    body=body,
                    chat_id=chat_id,
                    media_file_id=media_file_id,
                    media_type=media_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Inbox send failed: %s", exc)

        await session.flush()
        await _push_dialog_to_crm(dialog)
        await _push_message(
            chat_id,
            "in",
            inbound_text,
            tg_message_id=message.message_id,
        )

        if _is_blocked(dialog, now):
            await session.commit()
            return

        mode = effective_reply_mode(cfg, now)
        from app.bot.timeutil import is_future

        if dialog.state == "HUMAN_TAKEOVER" and is_future(dialog.takeover_until, relative_to=now):
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
            last_outbound_at=dialog.last_outbound_at,
        )

        dialog.state = result.new_state
        dialog.brief_json = dumps_brief(result.brief)
        if result.brief.get("niche"):
            dialog.niche = result.brief["niche"]
        if result.escalate and result.new_state == "HUMAN_TAKEOVER":
            # Window so Mini App / inbox show «вы ведёте», and auto-expire
            dialog.takeover_until = now + timedelta(hours=2)

        await _sync_crm_events(dialog, cfg, result.crm_events, message)

        if (
            cfg.get("crm_sync", True)
            and crm.enabled
            and dialog.crm_lead_id
            and result.brief
        ):
            try:
                patch = brief_to_crm_patch(
                    result.brief,
                    sales_depth=cfg.get("sales_depth") or "full_tz",
                    stage=result.new_state,
                )
                patch["qualification_json"] = dumps_brief(brief_for_crm_json(result.brief))
                await crm.patch(dialog.crm_lead_id, patch)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CRM patch brief failed: %s", exc)
                if "404" in str(exc):
                    dialog.crm_lead_id = None

        if result.escalate:
            if (
                cfg.get("crm_sync", True)
                and crm.enabled
                and dialog.crm_lead_id
                and result.escalate_reason != "tz_confirmed"
            ):
                try:
                    await crm.post_event(
                        dialog.crm_lead_id,
                        external_event_id=(
                            f"tg:{chat_id}:{message.message_id}:escalation:"
                            f"{result.escalate_reason or 'need_human'}"
                        ),
                        event_type="escalation",
                        note=(
                            f"Эскалация: {result.escalate_reason or 'need_human'} · "
                            f"стадия {result.new_state}"
                        ),
                        patch=brief_to_crm_patch(
                            result.brief,
                            sales_depth=cfg.get("sales_depth") or "full_tz",
                            stage=result.new_state,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("CRM escalation event failed: %s", exc)
            if settings.owner_chat_id:
                from app.bot.labels import reason_ru, stage_ru

                await bot.send_message(
                    settings.owner_chat_id,
                    (
                        "🔔 Нужен человек\n\n"
                        f"Клиент: {name}\n"
                        f"Почему: {reason_ru(result.escalate_reason)}\n"
                        f"Сейчас: {stage_ru(result.new_state)}\n\n"
                        f"Кратко:\n«{(user_text or '')[:200]}»"
                    ),
                    reply_markup=inbox_keyboard(
                        chat_id, bot_active=_bot_active_for_inbox(dialog)
                    ),
                )
            await _log_event(
                session, "escalation", chat_id, {"reason": result.escalate_reason}
            )

        reply = result.reply
        if reply:
            ok, reason = guard_client_text(reply)
            if not ok:
                logger.warning("Outbound blocked by guard (%s)", reason)
                reply = (
                    "Зафиксируем задачу коротко ✍️\n\n"
                    "Напишите «1» (сайт/лендинг) или «2» (бот/автоматизация) — "
                    "дальше менеджер продолжит."
                )

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
            await _push_message(chat_id, "out", reply)
        elif reply and (result.assist_only or mode == "ASSIST"):
            await _push_message(chat_id, "out", f"[черновик] {reply}")
            if settings.owner_chat_id:
                await bot.send_message(
                    settings.owner_chat_id,
                    f"Черновик для {name}:\n\n{reply}",
                    reply_markup=inbox_keyboard(
                        chat_id, bot_active=_bot_active_for_inbox(dialog)
                    ),
                )

        await _log_event(
            session,
            "state_transition",
            chat_id,
            {"to": result.new_state},
        )
        await session.commit()
        await _push_dialog_to_crm(dialog)

        await _push_dialog_to_crm(dialog)










