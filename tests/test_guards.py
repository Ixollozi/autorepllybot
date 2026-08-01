from app.brain.guards import contains_deadline_promise, contains_price, guard_client_text


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


def test_allows_clean():
    ok, reason = guard_client_text(
        "Итого формат лендинг, главное действие — заявка. Всё верно?"
    )
    assert ok is True
    assert reason == ""
