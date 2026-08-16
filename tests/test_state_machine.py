from app.brain.state_machine import DialogState, after_q3, next_after_fork
from app.brain.sales import build_tz_summary, parse_fork, is_tz_confirm


def test_fork_parser():
    assert parse_fork("1") == "1"
    assert parse_fork("давайте 2") == "2"
    assert parse_fork("привет") is None


def test_tz_confirm():
    assert is_tz_confirm("да, всё верно")
    assert not is_tz_confirm("нет, поправьте разделы")


def test_depth_transitions():
    assert next_after_fork("combo") == DialogState.HUMAN_TAKEOVER
    assert next_after_fork("full_tz") == DialogState.BRIEF_Q1
    assert after_q3("brief") == DialogState.HUMAN_TAKEOVER
    assert after_q3("full_tz") == DialogState.BRIEF_Q4


def test_tz_summary_no_price():
    text = build_tz_summary(
        {"fork": "landing_lead", "q1": "заявка", "q2": "лого", "q3": "главная"}
    )
    assert "лендинг" in text.lower()
    assert "стоимость" not in text.lower()
    assert "сум" not in text.lower()
    assert "$" not in text
    assert "коммерц" in text.lower()


def test_parse_fork_natural():
    assert parse_fork("нужен сайт для клиники") == "1"
    assert parse_fork("хотим телеграм бота") == "2"
    assert parse_fork("и сайт и бот") is None
    assert parse_fork("1") == "1"
