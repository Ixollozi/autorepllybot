"""Sales dialog state machine."""

from __future__ import annotations

from enum import StrEnum


class DialogState(StrEnum):
    NEW = "NEW"
    GREETING_QUALIFY = "GREETING_QUALIFY"
    MSG1_COMBO_SENT = "MSG1_COMBO_SENT"
    WAIT_FORK = "WAIT_FORK"
    BRIEF_Q1 = "BRIEF_Q1"
    BRIEF_Q2 = "BRIEF_Q2"
    BRIEF_Q3 = "BRIEF_Q3"
    BRIEF_Q4 = "BRIEF_Q4"
    TZ_DRAFT_SENT = "TZ_DRAFT_SENT"
    WAIT_TZ_CONFIRM = "WAIT_TZ_CONFIRM"
    TZ_CONFIRMED = "TZ_CONFIRMED"
    OBJECTION_HANDLING = "OBJECTION_HANDLING"
    NURTURE = "NURTURE"
    DISQUALIFIED = "DISQUALIFIED"
    HUMAN_TAKEOVER = "HUMAN_TAKEOVER"
    CLOSED = "CLOSED"


ACTIVE_SALES = {
    DialogState.NEW,
    DialogState.GREETING_QUALIFY,
    DialogState.MSG1_COMBO_SENT,
    DialogState.WAIT_FORK,
    DialogState.BRIEF_Q1,
    DialogState.BRIEF_Q2,
    DialogState.BRIEF_Q3,
    DialogState.BRIEF_Q4,
    DialogState.TZ_DRAFT_SENT,
    DialogState.WAIT_TZ_CONFIRM,
    DialogState.OBJECTION_HANDLING,
    DialogState.NURTURE,
}

TERMINAL = {
    DialogState.TZ_CONFIRMED,
    DialogState.DISQUALIFIED,
    DialogState.HUMAN_TAKEOVER,
    DialogState.CLOSED,
}


def next_after_fork(sales_depth: str) -> DialogState:
    if sales_depth in ("ack", "combo"):
        return DialogState.HUMAN_TAKEOVER
    return DialogState.BRIEF_Q1


def next_brief(state: DialogState, sales_depth: str) -> DialogState:
    order = [
        DialogState.BRIEF_Q1,
        DialogState.BRIEF_Q2,
        DialogState.BRIEF_Q3,
        DialogState.BRIEF_Q4,
    ]
    if state not in order:
        return DialogState.BRIEF_Q1
    idx = order.index(state)
    if sales_depth == "brief" and idx >= 2:
        return DialogState.HUMAN_TAKEOVER
    if idx + 1 < len(order):
        # Q4 optional for full_tz — still ask then draft
        return order[idx + 1]
    return DialogState.TZ_DRAFT_SENT


def after_q3(sales_depth: str) -> DialogState:
    if sales_depth == "brief":
        return DialogState.HUMAN_TAKEOVER
    if sales_depth == "full_tz":
        return DialogState.BRIEF_Q4
    return DialogState.HUMAN_TAKEOVER
