from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DEFAULT_SETTINGS, AppSettings


SETTINGS_KEY = "global"


async def get_settings_dict(session: AsyncSession) -> dict[str, Any]:
    row = await session.scalar(
        select(AppSettings).where(AppSettings.key == SETTINGS_KEY)
    )
    if row is None:
        data = deepcopy(DEFAULT_SETTINGS)
        session.add(
            AppSettings(key=SETTINGS_KEY, value_json=json.dumps(data, ensure_ascii=False))
        )
        await session.commit()
        return data
    try:
        data = json.loads(row.value_json)
    except json.JSONDecodeError:
        data = deepcopy(DEFAULT_SETTINGS)
    # merge defaults for new keys
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update(data)
    if "stt" in data and isinstance(data["stt"], dict):
        merged["stt"] = {**DEFAULT_SETTINGS["stt"], **data["stt"]}
    if "work_hours" in data and isinstance(data["work_hours"], dict):
        merged["work_hours"] = {**DEFAULT_SETTINGS["work_hours"], **data["work_hours"]}
    if "limits" in data and isinstance(data["limits"], dict):
        merged["limits"] = {**DEFAULT_SETTINGS["limits"], **data["limits"]}
    return merged


async def update_setting(session: AsyncSession, key: str, value: Any) -> dict[str, Any]:
    data = await get_settings_dict(session)
    data[key] = value
    row = await session.scalar(
        select(AppSettings).where(AppSettings.key == SETTINGS_KEY)
    )
    payload = json.dumps(data, ensure_ascii=False)
    if row is None:
        session.add(AppSettings(key=SETTINGS_KEY, value_json=payload))
    else:
        row.value_json = payload
    await session.commit()
    return data


def is_night(settings: dict[str, Any], now: datetime | None = None) -> bool:
    wh = settings.get("work_hours") or DEFAULT_SETTINGS["work_hours"]
    tz_name = wh.get("tz") or "Asia/Tashkent"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Tashkent")
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    start_s = wh.get("start") or "09:00"
    end_s = wh.get("end") or "21:00"
    start = time.fromisoformat(start_s)
    end = time.fromisoformat(end_s)
    t = now.timetz().replace(tzinfo=None)
    if start <= end:
        return not (start <= t < end)
    # overnight window
    return end <= t < start


def effective_reply_mode(settings: dict[str, Any], now: datetime | None = None) -> str:
    mode = settings.get("reply_mode") or "AUTO"
    if mode != "AUTO":
        return mode
    if not is_night(settings, now):
        return "AUTO"
    night = settings.get("night_policy") or "full_auto"
    if night == "full_auto":
        return "AUTO"
    if night == "ack_only":
        return "ACK_ONLY"
    if night == "silent":
        return "SILENT"
    if night == "assist_night":
        return "ASSIST"
    return "AUTO"
