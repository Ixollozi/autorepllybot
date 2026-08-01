from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.db.session import SessionLocal
from app.bot.settings_store import get_settings_dict

logger = logging.getLogger("nst.autoreply.crm")


class CrmClient:
    def __init__(self) -> None:
        self.base = settings.crm_base_url.rstrip("/")
        self.api_key = settings.autoreply_api_key
        self._keys_cache: dict[str, Any] | None = None
        self._keys_expires: datetime | None = None

    async def refresh_from_db(self) -> None:
        """Prefer values saved via /crm_key /crm_url over .env."""
        async with SessionLocal() as session:
            cfg = await get_settings_dict(session)
        url = (cfg.get("crm_base_url") or "").strip() or settings.crm_base_url
        key = (cfg.get("crm_api_key") or "").strip() or settings.autoreply_api_key
        self.base = url.rstrip("/")
        self.api_key = key
        self._keys_cache = None
        self._keys_expires = None

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base)

    def masked_key(self) -> str:
        k = self.api_key or ""
        if len(k) <= 4:
            return "****" if k else "—"
        return f"...{k[-4:]}"

    async def get_llm_keys(self, force: bool = False) -> dict[str, Any]:
        await self.refresh_from_db()
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._keys_cache
            and self._keys_expires
            and now < self._keys_expires
        ):
            return self._keys_cache

        empty = {
            "groq": {"model": settings.groq_model, "keys": []},
            "gemini": {"model": settings.gemini_model, "keys": []},
            "ttl_sec": 300,
        }

        if not self.enabled:
            return self._env_fallback_keys(empty)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base}/api/integrations/autoreply/llm-keys",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("CRM llm-keys failed: %s — using env fallback", exc)
            return self._env_fallback_keys(empty)

        # merge env fallback if CRM returned empty pools
        if not (data.get("groq") or {}).get("keys") and not (data.get("gemini") or {}).get(
            "keys"
        ):
            data = self._env_fallback_keys(data)

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

    def _env_fallback_keys(self, base: dict[str, Any]) -> dict[str, Any]:
        """Local .env GROQ_/GEMINI_ for demo when CRM unavailable."""
        out = dict(base)
        groq_keys = [k for k in [settings.groq_api_key] if k]
        gemini_keys = [k for k in [settings.gemini_api_key] if k]
        # also support comma-separated
        if settings.groq_api_keys:
            groq_keys = [x.strip() for x in settings.groq_api_keys.split(",") if x.strip()]
        if settings.gemini_api_keys:
            gemini_keys = [
                x.strip() for x in settings.gemini_api_keys.split(",") if x.strip()
            ]
        out["groq"] = {
            "model": settings.groq_model,
            "keys": groq_keys or list((base.get("groq") or {}).get("keys") or []),
        }
        out["gemini"] = {
            "model": settings.gemini_model,
            "keys": gemini_keys or list((base.get("gemini") or {}).get("keys") or []),
        }
        return out

    async def lookup(self, telegram: str) -> dict | None:
        await self.refresh_from_db()
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
        await self.refresh_from_db()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/upsert",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def patch(self, lead_id: int, payload: dict[str, Any]) -> dict:
        await self.refresh_from_db()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self.base}/api/integrations/autoreply/{lead_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def add_note(self, lead_id: int, text: str) -> dict:
        await self.refresh_from_db()
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
        await self.refresh_from_db()
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

    async def get_settings(self) -> dict[str, Any] | None:
        await self.refresh_from_db()
        if not self.enabled:
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base}/api/integrations/autoreply/settings",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def heartbeat(
        self, *, business_ok: bool | None = None, version: str | None = None
    ) -> dict[str, Any] | None:
        await self.refresh_from_db()
        if not self.enabled:
            return None
        body: dict[str, Any] = {}
        if business_ok is not None:
            body["business_ok"] = business_ok
        if version:
            body["version"] = version
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/heartbeat",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def upsert_dialog(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        await self.refresh_from_db()
        if not self.enabled:
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/dialogs/upsert",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def claim_setup(self, code: str, *, base_url: str | None = None) -> dict[str, Any]:
        """Bootstrap CRM URL + API key via one-time Mini App claim code (no prior key)."""
        base = (base_url or self.base or settings.crm_base_url).rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/api/integrations/autoreply/claim",
                json={"code": code},
            )
            resp.raise_for_status()
            return resp.json()

    async def append_message(
        self,
        *,
        chat_id: int,
        role: str,
        text: str,
        tg_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        await self.refresh_from_db()
        if not self.enabled or not (text or "").strip():
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/integrations/autoreply/dialogs/messages/one",
                headers=self._headers(),
                json={
                    "chat_id": chat_id,
                    "role": role,
                    "text": text[:8000],
                    "tg_message_id": tg_message_id,
                },
            )
            resp.raise_for_status()
            return resp.json()


crm = CrmClient()
