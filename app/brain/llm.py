"""LLM client: Groq primary, Gemini fallback, keys from CRM."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.crm.client import crm

logger = logging.getLogger("nst.autoreply.llm")


class LlmError(RuntimeError):
    pass


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.6,
    max_tokens: int = 700,
) -> str:
    keys_payload = await crm.get_llm_keys()
    groq = keys_payload.get("groq") or {}
    gemini = keys_payload.get("gemini") or {}

    providers: list[tuple[str, str, list[str]]] = [
        ("groq", groq.get("model") or "llama-3.3-70b-versatile", list(groq.get("keys") or [])),
        (
            "gemini",
            gemini.get("model") or "gemini-2.0-flash",
            list(gemini.get("keys") or []),
        ),
    ]

    last_err: Exception | None = None
    for provider, model, keys in providers:
        if not keys:
            continue
        for key in keys:
            try:
                text = await _openai_compatible(
                    provider=provider,
                    api_key=key,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if text.strip():
                    return text.strip()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning("%s key failed: %s", provider, exc)
                continue
    raise LlmError(f"All LLM providers failed: {last_err}")


async def _openai_compatible(
    *,
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    if provider == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
    else:
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 429:
            raise LlmError("429 rate limit")
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]
