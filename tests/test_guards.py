from app.brain.guards import (
    contains_deadline_promise,
    contains_foreign_script,
    contains_price,
    guard_client_text,
)
from app.brain.offtopic import asks_if_bot


def test_blocks_price():
    ok, reason = guard_client_text("Сайт будет от 500$")
    assert ok is False
    assert reason == "price"
    assert contains_price("стоимость 3 000 000 сум")


def test_blocks_deadline():
    ok, reason = guard_client_text("Сдадим за 7 дней")
    assert ok is False
    assert reason == "deadline"
    assert contains_deadline_promise("готово через 3 дня")


def test_blocks_cjk_corruption():
    text = "когда доходим до細алей и договора"
    assert contains_foreign_script(text) is True
    ok, reason = guard_client_text(text)
    assert ok is False
    assert reason == "foreign_script"


def test_allows_clean():
    ok, reason = guard_client_text(
        "Итого формат лендинг, главное действие — заявка. Всё верно?"
    )
    assert ok is True
    assert reason == ""


def test_asks_iiishka():
    assert asks_if_bot("ты иишка?") is True
    assert asks_if_bot("ты бот?") is True


def test_hostile():
    from app.brain.offtopic import is_hostile

    assert is_hostile("Ой, иди нахуй") is True
    assert is_hostile("нужен сайт") is False
