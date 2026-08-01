"""Off-topic / 'are you a bot' detectors."""

from __future__ import annotations

import re

OFFTOPIC_RE = re.compile(
    r"(?i)("
    r"напиши\s+(стих|код|сочинен|эссе|перевод)|"
    r"расскажи\s+анекдот|"
    r"поболтаем|"
    r"кто\s+победит|"
    r"прогноз\s+погод|"
    r"рецепт\s+|"
    r"домашн\w+\s+задани"
    r")"
)

BOT_ASK_RE = re.compile(
    r"(?i)("
    r"ты\s+(бот|ии|ai|нейросет|chatgpt|gpt)|"
    r"вы\s+(бот|ии|робот)|"
    r"это\s+(бот|ии)|"
    r"докажи\s+что\s+ты\s+(человек|живой)|"
    r"are\s+you\s+(a\s+)?bot"
    r")"
)

PRICE_ASK_RE = re.compile(
    r"(?i)("
    r"сколько\s+(стоит|будет|цена)|"
    r"какой\s+прайс|"
    r"прайс\s*лист|"
    r"цена\s*\?|"
    r"бюджет\s*\?"
    r")"
)

MANAGER_RE = re.compile(
    r"(?i)(менеджер|человек|оператор|директор|созвон|позвоните|наберите)"
)


def is_offtopic(text: str) -> bool:
    return bool(OFFTOPIC_RE.search(text or ""))


def asks_if_bot(text: str) -> bool:
    return bool(BOT_ASK_RE.search(text or ""))


def asks_price(text: str) -> bool:
    return bool(PRICE_ASK_RE.search(text or ""))


def asks_manager(text: str) -> bool:
    return bool(MANAGER_RE.search(text or ""))


OFFTOPIC_REPLY = (
    "Я по рабочим вопросам по сайтам/ботам/заявкам — "
    "давайте вернёмся к вашей задаче. "
    "Если нужен живой менеджер — напишите «менеджер», подключу."
)

BOT_ASK_REPLY_MASK = (
    "Тут переписку по проектам ведём быстро текстом; по условиям и договору "
    "подключается менеджер. Можем продолжить по задаче — или зовите менеджера."
)

BOT_ASK_REPLY_DISCLOSE = (
    "Да, это ассистент NST по проектам. По условиям и договору подключается менеджер. "
    "Продолжим по задаче?"
)
