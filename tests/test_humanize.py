from app.brain.humanize import detect_address_form, format_brief_context, push_turn


def test_address_ty_vy():
    brief: dict = {}
    assert detect_address_form("привет, подскажи", brief) == "ty"
    assert detect_address_form("Здравствуйте, подскажите", {}) == "vy"


def test_turns_memory():
    brief: dict = {}
    push_turn(brief, "user", "нужен сайт")
    push_turn(brief, "assistant", "ок, 1 или 2?")
    assert len(brief["_turns"]) == 2
    assert "сайт" in format_brief_context({"client_note": "нужен сайт"})
