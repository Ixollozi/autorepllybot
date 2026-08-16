import asyncio
from datetime import datetime, timedelta, timezone

from app.brain.loop_guard import (
    fork_nudge,
    is_explicit_restart,
    is_greeting,
    mark_allow_greeting_restart,
    mark_combo_sent,
    should_soft_restart,
    touch_inbound_streak,
)


def test_intent_split():
    assert is_greeting("привет")
    assert is_greeting("Здравствуйте!")
    assert not is_greeting("заново")
    assert is_explicit_restart("заново")
    assert is_explicit_restart("/reset")
    assert not is_explicit_restart("привет")


def test_streak():
    brief: dict = {}
    assert touch_inbound_streak(brief, "привет") == 1
    assert touch_inbound_streak(brief, "Привет!") == 2
    assert touch_inbound_streak(brief, "1") == 1
    assert touch_inbound_streak(brief, "1") == 2


def test_soft_restart_silence():
    brief: dict = {}
    mark_combo_sent(brief)
    now = datetime.now(timezone.utc)
    assert not should_soft_restart(
        brief=brief, last_outbound_at=now - timedelta(hours=1), now=now
    )
    assert should_soft_restart(
        brief=brief, last_outbound_at=now - timedelta(hours=13), now=now
    )


def test_soft_restart_after_wipe():
    brief: dict = {}
    mark_combo_sent(brief)
    mark_allow_greeting_restart(brief)
    now = datetime.now(timezone.utc)
    assert should_soft_restart(brief=brief, last_outbound_at=now, now=now)
    # flag consumed once
    assert not should_soft_restart(brief=brief, last_outbound_at=now, now=now)


def test_fork_nudge_escalates():
    brief: dict = {}
    r1, e1, c1 = fork_nudge(brief)
    r2, e2, c2 = fork_nudge(brief)
    r3, e3, c3 = fork_nudge(brief)
    assert c1 == 1 and not e1 and "1" in r1
    assert c2 == 2 and not e2 and ("крутимся" in r2 or "месте" in r2)
    assert c3 == 3 and e3 and "менеджера" in r3


def test_greeting_does_not_resend_combo():
    from app.brain.sales import _sales_turn_core

    async def _run():
        brief = {"niche": "generic", "_loop": {"combo_sent": True, "nudge_count": 0}}
        r1 = await _sales_turn_core(
            user_text="привет",
            state="WAIT_FORK",
            brief_raw=__import__("json").dumps(brief),
            settings={"sales_depth": "full_tz", "identity": "mask", "scope": "work_only"},
            mode="AUTO",
            last_outbound_at=datetime.now(timezone.utc),
        )
        assert r1.new_state == "WAIT_FORK"
        assert r1.reply and "combo" not in (r1.reply or "").lower()
        assert "1" in r1.reply and "2" in r1.reply
        assert "Делаем сайты" not in (r1.reply or "")

        r2 = await _sales_turn_core(
            user_text="привет",
            state=r1.new_state,
            brief_raw=__import__("json").dumps(r1.brief),
            settings={"sales_depth": "full_tz", "identity": "mask", "scope": "work_only"},
            mode="AUTO",
            last_outbound_at=datetime.now(timezone.utc),
        )
        assert "крутимся" in (r2.reply or "") or "месте" in (r2.reply or "")

        r3 = await _sales_turn_core(
            user_text="привет",
            state=r2.new_state,
            brief_raw=__import__("json").dumps(r2.brief),
            settings={"sales_depth": "full_tz", "identity": "mask", "scope": "work_only"},
            mode="AUTO",
            last_outbound_at=datetime.now(timezone.utc),
        )
        assert r3.escalate
        assert r3.new_state == "HUMAN_TAKEOVER"

    asyncio.run(_run())


def test_explicit_restart_resets():
    from app.brain.sales import _sales_turn_core

    async def _run():
        brief = {
            "niche": "dental",
            "fork": "landing_lead",
            "_loop": {"combo_sent": True, "nudge_count": 2},
        }
        r = await _sales_turn_core(
            user_text="заново",
            state="WAIT_FORK",
            brief_raw=__import__("json").dumps(brief),
            settings={"sales_depth": "full_tz", "identity": "mask", "scope": "work_only"},
            mode="AUTO",
            last_outbound_at=datetime.now(timezone.utc),
        )
        assert r.new_state == "WAIT_FORK"
        assert r.brief.get("fork") is None
        assert r.brief.get("niche") == "dental"

    asyncio.run(_run())
