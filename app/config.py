from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    owner_chat_id: int = 0

    crm_base_url: str = "https://crm.neosamptech.uz"
    autoreply_api_key: str = ""
    miniapp_url: str = "https://crm.neosamptech.uz/mini_app"

    # Optional local LLM fallback when CRM keys unavailable (demo)
    groq_api_key: str = ""
    groq_api_keys: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_api_keys: str = ""
    gemini_model: str = "gemini-2.0-flash"

    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    database_url: str = f"sqlite+aiosqlite:///{(ROOT / 'data' / 'autoreply.db').as_posix()}"
    log_level: str = "INFO"
    tz: str = "Asia/Tashkent"

    prompts_dir: Path = ROOT / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
