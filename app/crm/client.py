from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("nst.autoreply.crm")


class CrmClient:
    def __init__(self) -> None:
        self.base = settings.crm_base_url.rstrip("/")
        self.api_key = settings.autoreply_api_key
        self._keys_cache: dict[str, Any] | None = None
        self._keys_expires: datetime | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base)

    async def get_llm_keys(self, force: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._keys_cache
            and self._keys_expires
            and now < self._keys_expires
        ):
            return self._keys_cache
        if not self.enabled:
            return {
                "groq": {"model": "", "keys": []},
                "gemini": {"model": "", "keys": []},
                "ttl_sec": 300,
            }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base}/api/integrations/autoreply/llm-keys",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        ttl = int(data.get("ttl_sec") or 300)
        from datetime import timedelta

        self._keys_cache = data
        self._keys_expires = now + timedelta(seconds=max(60, ttl - 30))
        logger.info(
            "LLM keys refreshed groq=%d gemini=%d",
            len(data.get("groq", {}).get("keys") or []),
            len(data.get("gemini", {}).get("keys") or []),
        )
        return data

    async def lookup(self, telegram: str) -> dict | None:
        if not self.enabled:
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base}/api/integrations/autoreply/lookup",
                headers=self._headers(),
                params={"telegram": telegram},
            )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content or resp.text in ("null", ""):
                return None
            return resp.json()

    async def upsert(self, payload: dict[str, Any]) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/upsert",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def patch(self, lead_id: int, payload: dict[str, Any]) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self.base}/api/integrations/autoreply/{lead_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def add_note(self, lead_id: int, text: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/{lead_id}/notes",
                headers=self._headers(),
                json={"text": text},
            )
            resp.raise_for_status()
            return resp.json()

    async def post_event(
        self,
        lead_id: int,
        *,
        external_event_id: str,
        event_type: str,
        note: str | None = None,
        patch: dict | None = None,
        payload_json: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "external_event_id": external_event_id,
            "event_type": event_type,
        }
        if note:
            body["note"] = note
        if patch:
            body["patch"] = patch
        if payload_json:
            body["payload_json"] = payload_json
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/{lead_id}/events",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()


crm = CrmClient()
