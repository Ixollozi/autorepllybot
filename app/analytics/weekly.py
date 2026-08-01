from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import func, select

from app.config import settings
from app.db.models import AnalyticsEvent, Dialog
from app.db.session import SessionLocal

logger = logging.getLogger("nst.autoreply.weekly")


async def send_weekly_digest(bot: Bot) -> None:
    if not settings.owner_chat_id:
        return
    since = datetime.now(timezone.utc) - timedelta(days=7)
    async with SessionLocal() as session:
        total_in = await session.scalar(
            select(func.count())
            .select_from(AnalyticsEvent)
            .where(
                AnalyticsEvent.event_type == "msg_in",
                AnalyticsEvent.created_at >= since,
            )
        )
        tz_ok = await session.scalar(
            select(func.count())
            .select_from(AnalyticsEvent)
            .where(
                AnalyticsEvent.event_type == "escalation",
                AnalyticsEvent.created_at >= since,
            )
        )
        stt_ok = await session.scalar(
            select(func.count())
            .select_from(AnalyticsEvent)
            .where(
                AnalyticsEvent.event_type == "stt_ok",
                AnalyticsEvent.created_at >= since,
            )
        )
        confirmed = await session.scalar(
            select(func.count()).select_from(Dialog).where(Dialog.state == "TZ_CONFIRMED")
        )
    text = (
        "NST AutoReply — неделя\n"
        f"· Входящих событий: {total_in or 0}\n"
        f"· STT ok: {stt_ok or 0}\n"
        f"· Эскалаций: {tz_ok or 0}\n"
        f"· Диалогов с TZ_CONFIRMED (всего): {confirmed or 0}"
    )
    await bot.send_message(settings.owner_chat_id, text)
    logger.info("Weekly digest sent")
