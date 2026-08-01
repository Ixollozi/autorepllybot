from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def inbox_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Настройки", callback_data="settings:open"),
                InlineKeyboardButton(
                    text="Пауза чат", callback_data=f"chat:pause:{chat_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Взять диалог", callback_data=f"chat:takeover:{chat_id}"
                ),
                InlineKeyboardButton(
                    text="Бот снова", callback_data=f"chat:resume:{chat_id}"
                ),
            ],
        ]
    )


def settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    def row(label: str, key: str, value: str) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(
                text=f"{label}: {value}", callback_data=f"settings:cycle:{key}"
            )
        ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            row("Режим", "reply_mode", settings.get("reply_mode", "AUTO")),
            row("Ночь", "night_policy", settings.get("night_policy", "full_auto")),
            row("Кто я", "identity", settings.get("identity", "mask")),
            row("Глубина", "sales_depth", settings.get("sales_depth", "full_tz")),
            row("Follow-up", "nurture", settings.get("nurture", "soft")),
            row("Эскалация", "escalation", settings.get("escalation", "normal")),
            row("Язык", "language", settings.get("language", "auto")),
            row("Tempo", "tempo", settings.get("tempo", "human")),
            [
                InlineKeyboardButton(
                    text=f"STT: {'on' if (settings.get('stt') or {}).get('enabled', True) else 'off'}",
                    callback_data="settings:toggle:stt",
                ),
                InlineKeyboardButton(
                    text=f"CRM: {'on' if settings.get('crm_sync', True) else 'off'}",
                    callback_data="settings:toggle:crm_sync",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Тест карточки", callback_data="settings:test_card"
                ),
                InlineKeyboardButton(text="Статус", callback_data="settings:status"),
            ],
        ]
    )


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
