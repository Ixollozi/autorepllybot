from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DEFAULT_SETTINGS, AppSettings, Dialog


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


# Keys owned by CRM Mini App (bot keeps local CRM credentials).
CRM_PULLED_KEYS = {
    "reply_mode",
    "identity",
    "night_policy",
    "work_hours",
    "sales_depth",
    "nurture",
    "escalation",
    "language",
    "stt",
    "tempo",
    "scope",
    "crm_sync",
    "limits",
    "ignore_list",
}


async def apply_crm_settings(
    session: AsyncSession, remote: dict[str, Any]
) -> dict[str, Any]:
    """Merge CRM SoT settings into local cache; preserve crm_base_url / crm_api_key."""
    data = await get_settings_dict(session)
    for key in CRM_PULLED_KEYS:
        if key in remote:
            data[key] = remote[key]
    data["crm_settings_version"] = remote.get("version")
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


def _parse_iso_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def apply_pending_dialog_actions(
    session: AsyncSession, remote: dict[str, Any]
) -> list[str]:
    """Apply Mini App takeover/resume queue onto local dialogs. Returns applied ids."""
    actions = remote.get("pending_dialog_actions") or []
    if not actions:
        return []
    applied: list[str] = []
    for act in actions:
        if not isinstance(act, dict):
            continue
        action = str(act.get("action") or "")
        chat_id = act.get("chat_id")
        act_id = str(act.get("id") or "")
        if not act_id or chat_id is None:
            continue
        try:
            chat_id_i = int(chat_id)
        except (TypeError, ValueError):
            continue
        dialog = await session.scalar(select(Dialog).where(Dialog.chat_id == chat_id_i))
        if dialog is None:
            applied.append(act_id)
            continue
        if action == "resume":
            dialog.takeover_until = None
            dialog.paused_until = None
            if dialog.state == "HUMAN_TAKEOVER":
                dialog.state = "WAIT_FORK"
        elif action == "takeover":
            until = _parse_iso_dt(act.get("takeover_until"))
            dialog.takeover_until = until or (
                datetime.now(timezone.utc) + timedelta(hours=4)
            )
            dialog.state = "HUMAN_TAKEOVER"
        elif action == "wipe_transcript":
            from app.db.models import dumps_brief, loads_brief

            brief = loads_brief(dialog.brief_json)
            brief.pop("_turns", None)
            brief.pop("_voice", None)
            dialog.brief_json = dumps_brief(brief)
        else:
            continue
        applied.append(act_id)
    if applied:
        await session.commit()
    return applied


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
