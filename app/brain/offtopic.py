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
    r"ты\s+(бот|иишк\w*|ии|ai|нейросет\w*|chatgpt|gpt|робот)|"
    r"вы\s+(бот|иишк\w*|ии|робот|нейросет\w*)|"
    r"это\s+(бот|ии|нейросет\w*)|"
    r"докажи\s+что\s+ты\s+(человек|живой)|"
    r"are\s+you\s+(a\s+)?(bot|ai)|"
    r"you\s+(an?\s+)?ai"
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

HOSTILE_RE = re.compile(
    r"(?i)("
    r"иди\s+нахуй|пош[её]л\s+нахуй|нахуй|fuck\s+you|fuck\s+off|"
    r"отвали|заткнись|мудак|уебан|уёбок|бляд\w*|пидор|"
    r"^\s*cope\s*$"
    r")"
)


def is_offtopic(text: str) -> bool:
    return bool(OFFTOPIC_RE.search(text or ""))


def asks_if_bot(text: str) -> bool:
    return bool(BOT_ASK_RE.search(text or ""))


def asks_price(text: str) -> bool:
    return bool(PRICE_ASK_RE.search(text or ""))


def asks_manager(text: str) -> bool:
    return bool(MANAGER_RE.search(text or ""))


def is_hostile(text: str) -> bool:
    return bool(HOSTILE_RE.search(text or ""))


OFFTOPIC_REPLY = (
    "🙂 Я по рабочим вопросам — сайты, боты, заявки.\n\n"
    "Давайте вернёмся к задаче.\n"
    "Если нужен человек — напишите «менеджер»."
)

BOT_ASK_REPLY_MASK = (
    "👋 Тут быстро переписываемся по проектам текстом.\n\n"
    "📄 По условиям и договору подключается менеджер.\n\n"
    "Продолжим по задаче или зовём человека?"
)

BOT_ASK_REPLY_DISCLOSE = (
    "🤖 Да, это ассистент NST по переписке.\n\n"
    "По условиям подключается менеджер.\n"
    "Продолжим по задаче?"
)

HOSTILE_REPLY = (
    "Ок 👤\n\nПередаю менеджеру — он продолжит здесь, если будет задача."
)
