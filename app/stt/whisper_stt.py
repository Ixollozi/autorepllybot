from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("nst.autoreply.stt")

_model = None


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


async def transcribe_file(path: str | Path, language: str | None = "ru") -> tuple[str, str | None]:
    """Return (text, detected_lang). Runs in thread via to_thread."""
    import asyncio

    return await asyncio.to_thread(_transcribe_sync, str(path), language)


def _transcribe_sync(path: str, language: str | None) -> tuple[str, str | None]:
    model = _get_model()
    segments, info = model.transcribe(path, language=language, vad_filter=True)
    parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    text = " ".join(parts).strip()
    lang = getattr(info, "language", None)
    return text, lang


async def download_and_transcribe(
    bot,
    file_id: str,
    *,
    language: str | None = "ru",
) -> tuple[str, str | None]:
    file = await bot.get_file(file_id)
    suffix = Path(file.file_path or "audio.ogg").suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await bot.download_file(file.file_path, destination=tmp_path)
        return await transcribe_file(tmp_path, language=language)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
