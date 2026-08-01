from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.analytics.weekly import send_weekly_digest
from app.bot.handlers_business import router as business_router
from app.bot.handlers_owner import router as owner_router
from app.brain.nurture import run_nurture_tick
from app.config import settings
from app.crm.client import crm
from app.db.session import init_db


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


async def background_loops(bot: Bot) -> None:
    log = logging.getLogger("nst.autoreply.loops")
    last_weekly_day: int | None = None
    while True:
        try:
            await run_nurture_tick(bot)
        except Exception as exc:  # noqa: BLE001
            log.warning("nurture tick failed: %s", exc)
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(settings.tz))
            # Monday 10:00 local
            if now.weekday() == 0 and now.hour == 10 and last_weekly_day != now.toordinal():
                await send_weekly_digest(bot)
                last_weekly_day = now.toordinal()
        except Exception as exc:  # noqa: BLE001
            log.warning("weekly digest failed: %s", exc)
        await asyncio.sleep(300)


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
    else:
        log.warning("CRM not configured (AUTOREPLY_API_KEY empty)")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(owner_router)
    dp.include_router(business_router)

    asyncio.create_task(background_loops(bot))
    log.info("Polling started (Business + owner inbox)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
