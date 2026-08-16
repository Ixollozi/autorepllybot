"""Speech-to-text: Groq Whisper large-v3 primary, local faster-whisper fallback."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("nst.autoreply.stt")

_model = None

DOMAIN_PROMPT = (
    "Диалог с клиентом digital-агентства NeoSampTech (Ташкент). "
    "Частые слова: сайт, лендинг, Telegram-бот, заявка, запись, менеджер, "
    "стоматология, магазин, курс, вилка, ТЗ, окей, ладно."
)


@dataclass
class SttResult:
    text: str
    language: str | None = None
    provider: str = "local"
    avg_logprob: float | None = None

    @property
    def ok(self) -> bool:
        return bool((self.text or "").strip())

    @property
    def low_confidence(self) -> bool:
        if self.avg_logprob is None:
            return len((self.text or "").split()) <= 2
        return self.avg_logprob < -0.55


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        from app.config import settings

        logger.info(
            "Loading Whisper model=%s device=%s",
            settings.whisper_model,
            settings.whisper_device,
        )
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _model


async def _groq_keys() -> list[str]:
    try:
        from app.crm.client import crm

        await crm.refresh_from_db()
        if not crm.enabled:
            from app.config import settings

            if settings.groq_api_key:
                return [settings.groq_api_key]
            return []
        data = await crm.get_llm_keys()
        keys = list((data.get("groq") or {}).get("keys") or [])
        if keys:
            return keys
        from app.config import settings

        return [settings.groq_api_key] if settings.groq_api_key else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("STT: cannot load Groq keys: %s", exc)
        return []


async def _transcribe_groq(
    path: Path, *, language: str | None = "ru"
) -> SttResult | None:
    keys = await _groq_keys()
    if not keys:
        return None

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    data: dict[str, str] = {
        "model": "whisper-large-v3",
        "response_format": "verbose_json",
        "temperature": "0",
        "prompt": DOMAIN_PROMPT,
    }
    if language:
        data["language"] = language

    last_err: Exception | None = None
    for key in keys:
        try:
            headers = {"Authorization": f"Bearer {key}"}
            async with httpx.AsyncClient(timeout=90.0) as client:
                with path.open("rb") as f:
                    files = {"file": (path.name, f, "application/octet-stream")}
                    resp = await client.post(
                        url, headers=headers, data=data, files=files
                    )
            if resp.status_code >= 400:
                last_err = RuntimeError(f"Groq STT {resp.status_code}: {resp.text[:200]}")
                logger.warning("%s", last_err)
                continue
            body = resp.json()
            text = (body.get("text") or "").strip()
            segs = body.get("segments") or []
            avg = None
            if segs:
                vals = [float(s.get("avg_logprob", 0)) for s in segs]
                avg = sum(vals) / max(len(vals), 1)
            return SttResult(
                text=text,
                language=body.get("language") or language,
                provider="groq",
                avg_logprob=avg,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("Groq STT key failed: %s", exc)
            continue
    if last_err:
        logger.warning("Groq STT unavailable: %s", last_err)
    return None


def _transcribe_local_sync(path: str, language: str | None) -> SttResult:
    model = _get_model()
    segments, info = model.transcribe(
        path,
        language=language,
        vad_filter=True,
        beam_size=5,
        best_of=5,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=DOMAIN_PROMPT,
    )
    segs = list(segments)
    parts = [seg.text.strip() for seg in segs if seg.text.strip()]
    text = " ".join(parts).strip()
    avg = None
    if segs:
        avg = sum(float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in segs) / len(
            segs
        )
    return SttResult(
        text=text,
        language=getattr(info, "language", None),
        provider="local",
        avg_logprob=avg,
    )


async def transcribe_file(
    path: str | Path, language: str | None = "ru"
) -> tuple[str, str | None]:
    """Return (text, detected_lang). Prefer Groq, fallback local."""
    result = await transcribe_file_rich(path, language=language)
    return result.text, result.language


async def transcribe_file_rich(
    path: str | Path, language: str | None = "ru"
) -> SttResult:
    import asyncio

    p = Path(path)
    groq = await _transcribe_groq(p, language=language)
    if groq and groq.ok:
        logger.info(
            "STT groq ok len=%s logprob=%s",
            len(groq.text),
            groq.avg_logprob,
        )
        return groq

    local = await asyncio.to_thread(_transcribe_local_sync, str(p), language)
    logger.info(
        "STT local ok len=%s logprob=%s",
        len(local.text),
        local.avg_logprob,
    )
    return local


async def download_and_transcribe(
    bot,
    file_id: str,
    *,
    language: str | None = "ru",
) -> tuple[str, str | None]:
    result = await download_and_transcribe_rich(bot, file_id, language=language)
    return result.text, result.language


async def download_and_transcribe_rich(
    bot,
    file_id: str,
    *,
    language: str | None = "ru",
) -> SttResult:
    file = await bot.get_file(file_id)
    suffix = Path(file.file_path or "audio.ogg").suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await bot.download_file(file.file_path, destination=tmp_path)
        return await transcribe_file_rich(tmp_path, language=language)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
