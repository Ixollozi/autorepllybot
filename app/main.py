from __future__ import annotations

import asyncio
import logging
import sys
from datetime import timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo
from sqlalchemy import select

from app.analytics.weekly import send_weekly_digest
from app.bot.handlers_business import router as business_router
from app.bot.handlers_owner import router as owner_router
from app.bot.keyboards import miniapp_url
from app.bot.settings_store import apply_crm_settings
from app.brain.nurture import run_nurture_tick
from app.config import settings
from app.crm.client import crm
from app.db.models import BusinessConnectionRow
from app.db.session import SessionLocal, init_db


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


async def pull_crm_settings_once(log: logging.Logger) -> None:
    if not crm.enabled:
        return
    try:
        remote = await crm.get_settings()
        if not remote:
            return
        async with SessionLocal() as session:
            await apply_crm_settings(session, remote)
        log.info(
            "CRM settings pulled version=%s mode=%s",
            remote.get("version"),
            remote.get("reply_mode"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("CRM settings pull failed: %s", exc)


async def heartbeat_once(log: logging.Logger) -> None:
    if not crm.enabled:
        return
    try:
        async with SessionLocal() as session:
            conn = await session.scalar(
                select(BusinessConnectionRow)
                .where(BusinessConnectionRow.is_enabled.is_(True))
                .limit(1)
            )
        business_ok = bool(conn and conn.can_reply) if conn else None
        await crm.heartbeat(business_ok=business_ok, version="1.0")
    except Exception as exc:  # noqa: BLE001
        log.warning("CRM heartbeat failed: %s", exc)


async def background_loops(bot: Bot) -> None:
    log = logging.getLogger("nst.autoreply.loops")
    last_weekly_day: int | None = None
    tick = 0
    while True:
        tick += 1
        try:
            await run_nurture_tick(bot)
        except Exception as exc:  # noqa: BLE001
            log.warning("nurture tick failed: %s", exc)

        # Pull Mini App settings every cycle (~5 min) + heartbeat
        await pull_crm_settings_once(log)
        await heartbeat_once(log)

        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            try:
                tz = ZoneInfo(settings.tz)
            except Exception:
                tz = timezone.utc
            now = datetime.now(tz)
            if now.weekday() == 0 and now.hour == 10 and last_weekly_day != now.toordinal():
                await send_weekly_digest(bot)
                last_weekly_day = now.toordinal()
        except Exception as exc:  # noqa: BLE001
            log.warning("weekly digest failed: %s", exc)
        await asyncio.sleep(300)


async def set_menu_button(bot: Bot, log: logging.Logger) -> None:
    url = miniapp_url()
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Пульт",
                web_app=WebAppInfo(url=url),
            )
        )
        log.info("Menu button → %s", url)
    except Exception as exc:  # noqa: BLE001
        log.warning("set_chat_menu_button failed: %s", exc)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("nst.autoreply")
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is required")

    await init_db()
    log.info("DB ready")

    if crm.enabled:
        try:
            keys = await crm.get_llm_keys(force=True)
            log.info(
                "CRM LLM keys: groq=%d gemini=%d",
                len((keys.get("groq") or {}).get("keys") or []),
                len((keys.get("gemini") or {}).get("keys") or []),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("CRM llm-keys unavailable at startup: %s", exc)
        await pull_crm_settings_once(log)
    else:
        log.warning("CRM not configured (AUTOREPLY_API_KEY empty)")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await set_menu_button(bot, log)

    dp = Dispatcher()
    dp.include_router(owner_router)
    dp.include_router(business_router)

    asyncio.create_task(background_loops(bot))
    log.info("Polling started (Business + owner inbox + Mini App SoT)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
