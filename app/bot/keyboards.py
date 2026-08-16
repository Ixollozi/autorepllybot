from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings


def miniapp_url(path: str = "") -> str:
    base = (settings.miniapp_url or "https://crm.neosamptech.uz/mini_app").rstrip("/")
    if not path:
        return base
    return f"{base}{path if path.startswith('?') or path.startswith('/') else '/' + path}"


def inbox_keyboard(chat_id: int, *, bot_active: bool = True) -> InlineKeyboardMarkup:
    """Escalation/voice card actions. Active mode marked with ✅."""
    if bot_active:
        take_text = "Взять диалог"
        bot_text = "Бот отвечает ✅"
    else:
        take_text = "Вы ведёте ✅"
        bot_text = "Бот снова"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть пульт",
                    web_app=WebAppInfo(url=miniapp_url(f"?dialog={chat_id}")),
                )
            ],
            [
                InlineKeyboardButton(
                    text=take_text, callback_data=f"chat:takeover:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=bot_text, callback_data=f"chat:resume:{chat_id}"
                ),
            ],
        ]
    )


def owner_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть пульт",
                    web_app=WebAppInfo(url=miniapp_url()),
                )
            ]
        ]
    )


# Kept for rare callback fallbacks — Mini App is the real settings UI.
def settings_keyboard(_settings_dict: dict) -> InlineKeyboardMarkup:
    return owner_home_keyboard()


SETTINGS_CYCLES = {
    "reply_mode": ["AUTO", "ASSIST", "MANUAL"],
    "night_policy": ["full_auto", "ack_only", "silent", "assist_night"],
    "identity": ["mask", "disclose", "disclose_on_ask"],
    "sales_depth": ["ack", "combo", "brief", "full_tz"],
    "nurture": ["off", "soft", "active"],
    "escalation": ["paranoid", "normal", "late"],
    "language": ["auto", "ru", "uz", "mirror"],
    "tempo": ["instant", "human", "slow"],
}
