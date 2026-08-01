"""Output guards: block prices and delivery deadlines in client-facing text."""

from __future__ import annotations

import re

PRICE_RE = re.compile(
    r"(?i)("
    r"\$\s*\d|"
    r"\d[\d\s]{0,12}\s*(usd|\$|у\.?\s*е\.?|доллар|сум|so'?m|сумм)|"
    r"(цена|стоимость|прайс|предоплат\w*|оплат\w*|бюджет|скидк\w*)|"
    r"сколько\s+(стоит|будет)|"
    r"от\s+\d[\d\s]{2,}\s*(usd|\$|сум)|"
    r"пакет\s+за\s+\d|"
    r"без\s+цены"
    r")"
)

DEADLINE_RE = re.compile(
    r"(?i)("
    r"за\s+\d+\s*(день|дня|дней|недел|час)|"
    r"сдад(им|у|ете)\s+(за|к|через)|"
    r"готово\s+(за|через)\s+\d|"
    r"срок\s+сдачи\s*[:\-]?\s*\d|"
    r"к\s+(понедельник|вторник|сред|четверг|пятниц|суббот|воскресень)"
    r")"
)


def contains_price(text: str) -> bool:
    return bool(PRICE_RE.search(text or ""))


def contains_deadline_promise(text: str) -> bool:
    return bool(DEADLINE_RE.search(text or ""))


def guard_client_text(text: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means must not send."""
    if contains_price(text):
        return False, "price"
    if contains_deadline_promise(text):
        return False, "deadline"
    return True, ""
