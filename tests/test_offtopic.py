from app.brain.offtopic import asks_if_bot, asks_price, is_offtopic


def test_offtopic():
    assert is_offtopic("напиши стих про осень")
    assert not is_offtopic("нужен сайт для клиники")


def test_bot_ask():
    assert asks_if_bot("ты бот?")
    assert asks_if_bot("are you a bot")


def test_price_ask():
    assert asks_price("сколько стоит лендинг?")
    assert not asks_price("какие разделы нужны")
