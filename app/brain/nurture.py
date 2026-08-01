from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select

from app.bot.settings_store import get_settings_dict
from app.db.models import Dialog
from app.db.session import SessionLocal

logger = logging.getLogger("nst.autoreply.nurture")

FOLLOWUP_TEXTS = {
    "WAIT_FORK": "На всякий случай: напишите «1» или «2» — так быстрее зафиксируем формат.",
    "BRIEF_Q1": "Остался короткий вопрос по главному действию посетителя — и сможем собрать ТЗ.",
    "BRIEF_Q2": "Если удобно — что из материалов уже есть (лого/фото/тексты)?",
    "BRIEF_Q3": "Уточните объём разделов — и соберу резюме задачи.",
    "BRIEF_Q4": "Если есть желаемая дата запуска — напишите, это для менеджера.",
    "WAIT_TZ_CONFIRM": "Проверьте резюме выше — всё верно? Напишите «да» или что поправить.",
}


async def run_nurture_tick(bot: Bot) -> None:
    async with SessionLocal() as session:
        cfg = await get_settings_dict(session)
        nurture = cfg.get("nurture") or "soft"
        if nurture == "off":
            return
        now = datetime.now(timezone.utc)
        min_age = timedelta(hours=4 if nurture == "soft" else 3)
        rows = (
            await session.scalars(
                select(Dialog).where(
                    Dialog.state.in_(list(FOLLOWUP_TEXTS.keys())),
                    Dialog.last_inbound_at.is_not(None),
                )
            )
        ).all()
        for dialog in rows:
            if dialog.takeover_until and dialog.takeover_until > now:
                continue
            if dialog.paused_until and dialog.paused_until > now:
                continue
            if not dialog.business_connection_id:
                continue
            if not dialog.last_inbound_at:
                continue
            last_in = dialog.last_inbound_at
            if last_in.tzinfo is None:
                last_in = last_in.replace(tzinfo=timezone.utc)
            if now - last_in < min_age:
                continue
            if dialog.last_followup_at:
                lf = dialog.last_followup_at
                if lf.tzinfo is None:
                    lf = lf.replace(tzinfo=timezone.utc)
                if now - lf < timedelta(hours=20):
                    continue
            if nurture == "soft" and (dialog.followup_count or 0) >= 2:
                continue
            if nurture == "active" and (dialog.followup_count or 0) >= 3:
                continue
            text = FOLLOWUP_TEXTS.get(dialog.state)
            if not text:
                continue
            try:
                await bot.send_message(
                    dialog.chat_id,
                    text,
                    business_connection_id=dialog.business_connection_id,
                )
                dialog.last_followup_at = now
                dialog.followup_count = (dialog.followup_count or 0) + 1
                await session.commit()
                logger.info("Nurture sent chat=%s state=%s", dialog.chat_id, dialog.state)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Nurture failed chat=%s: %s", dialog.chat_id, exc)
                await session.rollback()
