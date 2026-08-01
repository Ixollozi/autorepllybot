from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


DEFAULT_SETTINGS: dict[str, Any] = {
    "reply_mode": "AUTO",
    "identity": "mask",
    "night_policy": "full_auto",
    "work_hours": {"tz": "Asia/Tashkent", "start": "09:00", "end": "21:00"},
    "sales_depth": "full_tz",
    "nurture": "soft",
    "escalation": "normal",
    "language": "auto",
    "stt": {
        "enabled": True,
        "voice": True,
        "video_note": True,
        "clean_profanity": False,
    },
    "tempo": "human",
    "scope": "work_only",
    "crm_sync": True,
    "crm_base_url": "",
    "crm_api_key": "",
    "limits": {"max_out_per_chat_hour": 8, "max_chars": 900},
    "ignore_list": [],
}


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BusinessConnectionRow(Base):
    __tablename__ = "business_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_chat_id: Mapped[int | None] = mapped_column(Integer)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Dialog(Base):
    __tablename__ = "dialogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    business_connection_id: Mapped[str | None] = mapped_column(String(128))
    telegram_username: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(64), default="NEW", index=True)
    brief_json: Mapped[str | None] = mapped_column(Text)
    crm_lead_id: Mapped[int | None] = mapped_column(Integer)
    takeover_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str | None] = mapped_column(String(8))
    niche: Mapped[str | None] = mapped_column(String(64))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (
        UniqueConstraint(
            "business_connection_id", "message_id", name="uq_biz_msg"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_connection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chat_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


def dumps_brief(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads_brief(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
