from __future__ import annotations

import logging
import re

from datetime import datetime

from app.brain.humanize import humanize_reply, push_turn
from app.brain.loop_guard import (
    brief_question_nudge,
    fork_nudge,
    is_explicit_restart,
    is_greeting,
    mark_combo_sent,
    should_soft_restart,
    touch_inbound_streak,
)
from app.brain.offtopic import (
    BOT_ASK_REPLY_DISCLOSE,
    BOT_ASK_REPLY_MASK,
    HOSTILE_REPLY,
    OFFTOPIC_REPLY,
    asks_if_bot,
    asks_manager,
    asks_price,
    is_hostile,
    is_offtopic,
)
from app.brain.state_machine import (
    DialogState,
    after_q3,
    next_after_fork,
)
from app.config import settings
from app.db.models import loads_brief

logger = logging.getLogger("nst.autoreply.sales")

BRIEF_QUESTIONS = {
    DialogState.BRIEF_Q1: (
        "Какое действие на сайте для вас главное — "
        "запись онлайн, заявка с телефоном, звонок или написать в Telegram?"
    ),
    DialogState.BRIEF_Q2: (
        "Что уже есть под рукой: лого, фото, тексты услуг, Instagram / 2GIS / сайт? "
        "Что есть — возьмём в работу."
    ),
    DialogState.BRIEF_Q3: (
        "По объёму: хватит главная + услуги + контакты, "
        "или ещё нужны разделы вроде каталога / команды / акций?"
    ),
    DialogState.BRIEF_Q4: (
        "К какой дате хотели бы запуститься? "
        "Это ориентир для менеджера — в резюме дату сдачи не фиксируем."
    ),
}


def _read_prompt(name: str) -> str:
    path = settings.prompts_dir / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def detect_niche(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("стомат", "клиник", "зуб", "dental")):
        return "dental"
    if any(w in t for w in ("магазин", "одежд", "ритейл", "shop", "товар")):
        return "retail"
    if any(w in t for w in ("учеб", "курс", "школ", "обучен", "центр")):
        return "edu"
    return "generic"


def combo_for_niche(niche: str) -> str:
    mapping = {
        "dental": "niche_combo_dental.md",
        "retail": "niche_combo_retail.md",
        "edu": "niche_combo_edu.md",
        "generic": "niche_combo_generic.md",
    }
    return _read_prompt(mapping.get(niche, "niche_combo_generic.md"))


def parse_fork(text: str) -> str | None:
    t = (text or "").strip().lower()
    if t in ("1", "1️⃣", "один", "первая", "первое"):
        return "1"
    if t in ("2", "2️⃣", "два", "вторая", "второе"):
        return "2"
    m = re.search(r"\b([12])\b", t)
    if m:
        return m.group(1)

    wants_site = any(
        w in t
        for w in (
            "лендинг",
            "landing",
            "сайт",
            "вебсайт",
            "веб-сайт",
            "webpage",
            "web site",
        )
    )
    wants_bot = any(
        w in t
        for w in (
            "бот",
            "bot",
            "автоматиз",
            "автоответ",
            "telegram-бот",
            "телеграм-бот",
            "тг бот",
        )
    )
    if wants_site and wants_bot:
        return None
    if wants_site:
        return "1"
    if wants_bot:
        return "2"
    return None


def absorb_client_signal(brief: dict, user_text: str) -> None:
    """Keep free-text context + refresh niche when client describes the task."""
    t = (user_text or "").strip()
    if len(t) < 12 or is_greeting(t) or is_explicit_restart(t):
        return
    brief["client_note"] = t[:400]
    niche = detect_niche(t)
    if niche != "generic":
        brief["niche"] = niche


def is_restart_intent(text: str) -> bool:
    """Backward-compatible: greeting or explicit restart phrase."""
    return is_greeting(text) or is_explicit_restart(text)


def is_tz_confirm(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(
        w in t
        for w in ("да", "верно", "всё так", "все так", "ок", "окей", "согласен", "подтверж", "yes")
    )


FORK_LABELS = {
    "landing_lead": "лендинг / сайт под заявки",
    "bot_or_site": "Telegram-бот / автоматизация",
}

NICHE_LABELS = {
    "dental": "стоматология",
    "retail": "ритейл / магазин",
    "edu": "учебный центр",
    "generic": "общая / не уточнена",
}

SCRIPT_OFFER_BY_FORK = {
    "landing_lead": "site",
    "bot_or_site": "bot",
}


def fork_label(fork: str | None) -> str:
    if not fork:
        return "—"
    return FORK_LABELS.get(fork, fork)


def niche_label(niche: str | None) -> str:
    if not niche:
        return "—"
    return NICHE_LABELS.get(niche, niche)


def script_offer_from_brief(brief: dict) -> str | None:
    return SCRIPT_OFFER_BY_FORK.get(str(brief.get("fork") or ""))


def infer_script_branch(brief: dict) -> str:
    """Map client signals → CRM script_branch S/W/P/D/N."""
    blob = " ".join(
        str(brief.get(k) or "")
        for k in ("client_note", "q1", "q2", "q3", "niche", "fork")
    ).lower()
    if any(w in blob for w in ("свой айти", "свой it", "свой разработ", "программист")):
        return "P"
    if any(w in blob for w in ("уже делают", "уже делают у", "другая компан", "подрядчик")):
        return "D"
    if any(
        w in blob
        for w in (
            "нет сайта",
            "без сайта",
            "сайта нет",
            "сайта не",
            "нема сайта",
        )
    ):
        return "S"
    if any(
        w in blob
        for w in (
            "есть сайт",
            "сайт есть",
            "наш сайт",
            "на сайте",
            "текущий сайт",
            "уже есть сайт",
        )
    ):
        return "W"
    # Cold TG / autoreply default — чаще вход «нет/слабый сайт»
    return "S"


def infer_script_score(brief: dict, *, sales_depth: str = "full_tz", stage: str = "") -> str:
    """A hot … D minimal — mirrors CRM script scores."""
    if stage in ("tz_confirmed", "WAIT_TZ_CONFIRM") and (
        brief.get("q1") or brief.get("fork")
    ):
        return "A"
    if sales_depth == "ack":
        return "D"
    if sales_depth in ("combo", "brief"):
        return "C"
    if brief.get("fork") and brief.get("q1"):
        return "B"
    return "B"


def script_fields_for_crm(
    brief: dict, *, sales_depth: str = "full_tz", stage: str = ""
) -> dict:
    fields: dict = {
        "script_branch": infer_script_branch(brief),
        "script_score": infer_script_score(brief, sales_depth=sales_depth, stage=stage),
    }
    offer = script_offer_from_brief(brief)
    if offer:
        fields["script_offer"] = offer
    return fields


def build_tz_summary(brief: dict) -> str:
    note = brief.get("client_note")
    extra = f"\n— от вас: {note}" if note else ""
    return (
        "Собрал коротко, как понял задачу:\n\n"
        f"— формат: {fork_label(brief.get('fork'))}\n"
        f"— главное действие: {brief.get('q1') or '—'}\n"
        f"— материалы: {brief.get('q2') or '—'}\n"
        f"— разделы: {brief.get('q3') or '—'}"
        f"{extra}\n\n"
        "Коммерцию и сроки сдачи тут не фиксируем — сначала задача, "
        "потом менеджер с вариантами.\n\n"
        "Всё так, или что-то поправить?"
    )


def format_crm_comment(brief: dict) -> str:
    """Human summary for CRM lead.comment (manager-facing)."""
    lines = [
        f"Формат: {fork_label(brief.get('fork'))}",
        f"Ниша: {niche_label(brief.get('niche'))}",
    ]
    if brief.get("q1"):
        lines.append(f"Главное действие: {brief['q1']}")
    if brief.get("q2"):
        lines.append(f"Материалы: {brief['q2']}")
    if brief.get("q3"):
        lines.append(f"Разделы: {brief['q3']}")
    if brief.get("client_timing_signal"):
        lines.append(f"Запуск (сигнал клиента): {brief['client_timing_signal']}")
    if brief.get("client_note"):
        lines.append(f"Своими словами: {brief['client_note']}")
    return "\n".join(lines)[:5000]


def format_crm_manager_note(brief: dict) -> str:
    """One structured note after TZ confirm — not the client chat copy."""
    return (
        "Автоответчик: бриф подтверждён\n"
        + format_crm_comment(brief)
    )[:5000]


def brief_for_crm_json(brief: dict) -> dict:
    """Drop internal loop/voice/turns meta before writing qualification_json."""
    skip = {"_loop", "_turns", "_voice"}
    return {k: v for k, v in brief.items() if k not in skip}


def brief_to_crm_patch(
    brief: dict, *, sales_depth: str = "full_tz", stage: str = ""
) -> dict:
    """Manager-facing fields to write on brief sync (caller adds qualification_json)."""
    patch: dict = {
        "comment": format_crm_comment(brief),
        **script_fields_for_crm(brief, sales_depth=sales_depth, stage=stage),
    }
    if brief.get("niche"):
        patch["niche"] = str(brief["niche"])[:128]
    return patch


ACK_NIGHT = (
    "Получили сообщение, спасибо 🌙\n\n"
    "Утром в рабочее время продолжим по задаче."
)

PRICE_BRIDGE = (
    "Чтобы дать нормальные варианты, сначала зафиксируем задачу ✍️\n\n"
    "Пара коротких вопросов — дальше менеджер.\n\n"
    "С чего начнём?\n"
    "1️⃣ лендинг / сайт под заявки\n"
    "2️⃣ бот / автоматизация"
)


class SalesResult:
    def __init__(
        self,
        reply: str | None,
        new_state: str,
        brief: dict,
        escalate: bool = False,
        escalate_reason: str = "",
        crm_events: list[dict] | None = None,
        assist_only: bool = False,
        skip_humanize: bool = False,
    ):
        self.reply = reply
        self.new_state = new_state
        self.brief = brief
        self.escalate = escalate
        self.escalate_reason = escalate_reason
        self.crm_events = crm_events or []
        self.assist_only = assist_only
        self.skip_humanize = skip_humanize


async def handle_sales_turn(
    *,
    user_text: str,
    state: str,
    brief_raw: str | None,
    settings: dict,
    mode: str,
    niche_hint: str | None = None,
    last_outbound_at: datetime | None = None,
) -> SalesResult:
    identity = (settings or {}).get("identity") or "mask"
    result = await _sales_turn_core(
        user_text=user_text,
        state=state,
        brief_raw=brief_raw,
        settings=settings,
        mode=mode,
        niche_hint=niche_hint,
        last_outbound_at=last_outbound_at,
    )
    push_turn(result.brief, "user", user_text)
    if result.reply and not result.skip_humanize:
        result.reply = await humanize_reply(
            result.reply,
            user_text=user_text,
            brief=result.brief,
            state=result.new_state,
            identity=identity,
        )
    if result.reply:
        push_turn(result.brief, "assistant", result.reply)
    return result


async def _sales_turn_core(
    *,
    user_text: str,
    state: str,
    brief_raw: str | None,
    settings: dict,
    mode: str,
    niche_hint: str | None = None,
    last_outbound_at: datetime | None = None,
) -> SalesResult:
    brief = loads_brief(brief_raw)
    sales_depth = settings.get("sales_depth") or "full_tz"
    identity = settings.get("identity") or "mask"
    scope = settings.get("scope") or "work_only"
    streak = touch_inbound_streak(brief, user_text)

    if mode in ("MANUAL", "SILENT", "TAKEOVER"):
        return SalesResult(None, state, brief)

    if mode == "ACK_ONLY":
        return SalesResult(ACK_NIGHT, state, brief)

    st = DialogState(state) if state in DialogState._value2member_map_ else DialogState.NEW

    # Restart policy — never treat every «привет» as a full funnel reset.
    if is_explicit_restart(user_text) and st not in (
        DialogState.NEW,
        DialogState.GREETING_QUALIFY,
    ):
        logger.info("Explicit restart from state=%s → NEW", st.value)
        kept_niche = brief.get("niche")
        brief = {"niche": kept_niche} if kept_niche else {}
        st = DialogState.NEW
    elif is_greeting(user_text) and st not in (
        DialogState.NEW,
        DialogState.GREETING_QUALIFY,
    ):
        if should_soft_restart(brief=brief, last_outbound_at=last_outbound_at):
            logger.info("Soft restart (silence/wipe) from state=%s → NEW", st.value)
            kept_niche = brief.get("niche")
            brief = {"niche": kept_niche} if kept_niche else {}
            st = DialogState.NEW
        elif st in (DialogState.MSG1_COMBO_SENT, DialogState.WAIT_FORK):
            reply, escalate, _ = fork_nudge(brief)
            return SalesResult(
                reply,
                DialogState.WAIT_FORK.value if not escalate else DialogState.HUMAN_TAKEOVER.value,
                brief,
                escalate=escalate,
                escalate_reason="loop_greeting_at_fork" if escalate else "",
            )
        elif st in (
            DialogState.BRIEF_Q1,
            DialogState.BRIEF_Q2,
            DialogState.BRIEF_Q3,
            DialogState.BRIEF_Q4,
        ):
            q = BRIEF_QUESTIONS[st]
            reply, escalate = brief_question_nudge(q, streak)
            return SalesResult(
                reply,
                st.value if not escalate else DialogState.HUMAN_TAKEOVER.value,
                brief,
                escalate=escalate,
                escalate_reason="loop_greeting_in_brief" if escalate else "",
            )
        elif st in (DialogState.TZ_DRAFT_SENT, DialogState.WAIT_TZ_CONFIRM):
            return SalesResult(
                "👋 Я на связи.\n\nПодтвердите резюме выше — «да», или напишите что поправить.",
                DialogState.WAIT_TZ_CONFIRM.value,
                brief,
            )
        else:
            return SalesResult(
                "👋 Я на связи.\n\nНапишите задачу или «менеджер» — подключу человека.",
                st.value,
                brief,
            )

    if is_hostile(user_text):
        return SalesResult(
            HOSTILE_REPLY,
            DialogState.HUMAN_TAKEOVER.value,
            brief,
            escalate=True,
            escalate_reason="hostile",
            skip_humanize=True,
        )

    if is_offtopic(user_text) and scope != "work_plus_smalltalk":
        return SalesResult(
            OFFTOPIC_REPLY,
            st.value,
            brief,
            escalate=True,
            escalate_reason="offtopic",
            skip_humanize=True,
        )

    if asks_if_bot(user_text):
        reply = (
            BOT_ASK_REPLY_DISCLOSE
            if identity in ("disclose", "disclose_on_ask")
            else BOT_ASK_REPLY_MASK
        )
        return SalesResult(
            reply,
            st.value,
            brief,
            escalate=True,
            escalate_reason="caught_or_bot_ask",
            skip_humanize=True,
        )

    if asks_manager(user_text):
        return SalesResult(
            "👤 Ок, подключаю менеджера — он напишет здесь по задаче.",
            DialogState.HUMAN_TAKEOVER.value,
            brief,
            escalate=True,
            escalate_reason="client_asked_manager",
            skip_humanize=True,
        )

    if asks_price(user_text) and st in (
        DialogState.NEW,
        DialogState.GREETING_QUALIFY,
        DialogState.MSG1_COMBO_SENT,
        DialogState.WAIT_FORK,
    ):
        return SalesResult(
            PRICE_BRIDGE,
            DialogState.WAIT_FORK.value,
            brief,
            skip_humanize=True,
        )

    if st in TERMINAL_BLOCK:
        return SalesResult(None, st.value, brief)

    crm_events: list[dict] = []

    # NEW / GREETING → send combo
    if st in (DialogState.NEW, DialogState.GREETING_QUALIFY):
        absorb_client_signal(brief, user_text)
        niche = niche_hint or brief.get("niche") or detect_niche(user_text)
        brief["niche"] = niche
        combo = combo_for_niche(niche)
        if sales_depth == "ack":
            reply = (
                "Здравствуйте! 👋\n\n"
                "На связи NeoSampTech.\n"
                "Получили сообщение — менеджер подключится по задаче."
            )
            return SalesResult(
                reply,
                DialogState.HUMAN_TAKEOVER.value,
                brief,
                escalate=True,
                escalate_reason="sales_depth_ack",
            )
        mark_combo_sent(brief)
        msg1_patch = {
            "msg1_sent": True,
            # В скрипте кейсы+вилка часто уже в Msg1-Combo
            "msg2_sent": True,
            "status": "Написал",
            **script_fields_for_crm(brief, sales_depth=sales_depth, stage="msg1"),
            "comment": format_crm_comment(brief),
        }
        if brief.get("niche"):
            msg1_patch["niche"] = str(brief["niche"])[:128]
        crm_events.append({"type": "msg1_sent", "patch": msg1_patch})
        return SalesResult(
            combo,
            DialogState.WAIT_FORK.value,
            brief,
            crm_events=crm_events,
            assist_only=(mode == "ASSIST"),
        )

    if st in (DialogState.MSG1_COMBO_SENT, DialogState.WAIT_FORK):
        absorb_client_signal(brief, user_text)
        fork = parse_fork(user_text)
        if not fork:
            reply, escalate, _ = fork_nudge(brief)
            return SalesResult(
                reply,
                DialogState.WAIT_FORK.value if not escalate else DialogState.HUMAN_TAKEOVER.value,
                brief,
                escalate=escalate,
                escalate_reason="loop_stuck_at_fork" if escalate else "",
                assist_only=(mode == "ASSIST"),
                skip_humanize=escalate,
            )
        brief["fork"] = "landing_lead" if fork == "1" else "bot_or_site"
        fork_patch: dict = {
            "msg1_reply": True,
            "msg2_replied": True,
            "status": "Ответил",
            "comment": format_crm_comment(brief),
            **script_fields_for_crm(brief, sales_depth=sales_depth, stage="fork"),
        }
        if brief.get("niche"):
            fork_patch["niche"] = str(brief["niche"])[:128]
        crm_events.append({"type": "msg1_reply", "patch": fork_patch})
        nxt = next_after_fork(sales_depth)
        if nxt == DialogState.HUMAN_TAKEOVER:
            return SalesResult(
                "✅ Ок, формат зафиксировал.\n\nДальше менеджер с вариантами.",
                nxt.value,
                brief,
                escalate=True,
                escalate_reason="sales_depth_combo",
                crm_events=crm_events,
            )
        q = BRIEF_QUESTIONS[DialogState.BRIEF_Q1]
        return SalesResult(
            f"✅ Ок, зафиксировал.\n\n{q}",
            DialogState.BRIEF_Q1.value,
            brief,
            crm_events=crm_events,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q1:
        brief["q1"] = user_text.strip()[:500]
        return SalesResult(
            f"Понял 👍\n\n{BRIEF_QUESTIONS[DialogState.BRIEF_Q2]}",
            DialogState.BRIEF_Q2.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q2:
        brief["q2"] = user_text.strip()[:500]
        return SalesResult(
            f"Отлично, это упрощает ✨\n\n{BRIEF_QUESTIONS[DialogState.BRIEF_Q3]}",
            DialogState.BRIEF_Q3.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q3:
        brief["q3"] = user_text.strip()[:500]
        nxt = after_q3(sales_depth)
        if nxt == DialogState.HUMAN_TAKEOVER:
            return SalesResult(
                "Спасибо, этого достаточно для старта. Менеджер продолжит с вариантами.",
                nxt.value,
                brief,
                escalate=True,
                escalate_reason="sales_depth_brief",
            )
        return SalesResult(
            BRIEF_QUESTIONS[DialogState.BRIEF_Q4],
            DialogState.BRIEF_Q4.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q4:
        brief["client_timing_signal"] = user_text.strip()[:500]
        summary = build_tz_summary(brief)
        timing = brief["client_timing_signal"]
        crm_events.append(
            {
                "type": "brief_timing",
                "note": f"Желаемый запуск (сигнал): {timing}",
                "patch": brief_to_crm_patch(
                    brief, sales_depth=sales_depth, stage="WAIT_TZ_CONFIRM"
                ),
            }
        )
        return SalesResult(
            summary,
            DialogState.WAIT_TZ_CONFIRM.value,
            brief,
            crm_events=crm_events,
            assist_only=(mode == "ASSIST"),
        )

    if st in (DialogState.TZ_DRAFT_SENT, DialogState.WAIT_TZ_CONFIRM):
        if is_tz_confirm(user_text):
            confirm_patch = brief_to_crm_patch(
                brief, sales_depth=sales_depth, stage="tz_confirmed"
            )
            confirm_patch["status"] = "Ответил"
            confirm_patch["outcome_step"] = "demo"
            crm_events.append(
                {
                    "type": "tz_confirmed",
                    "note": format_crm_manager_note(brief),
                    "patch": confirm_patch,
                }
            )
            return SalesResult(
                "✅ Супер, зафиксировал.\n\nСейчас менеджер продолжит с вариантами.",
                DialogState.TZ_CONFIRMED.value,
                brief,
                escalate=True,
                escalate_reason="tz_confirmed",
                crm_events=crm_events,
            )
        brief["q3"] = (brief.get("q3") or "") + f" | уточнение: {user_text.strip()[:200]}"
        summary = build_tz_summary(brief)
        return SalesResult(
            summary,
            DialogState.WAIT_TZ_CONFIRM.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    # fallback: send combo
    absorb_client_signal(brief, user_text)
    niche = niche_hint or brief.get("niche") or detect_niche(user_text)
    combo = combo_for_niche(niche)
    return SalesResult(
        combo,
        DialogState.WAIT_FORK.value,
        brief,
        assist_only=(mode == "ASSIST"),
    )


TERMINAL_BLOCK = {
    DialogState.TZ_CONFIRMED,
    DialogState.DISQUALIFIED,
    DialogState.HUMAN_TAKEOVER,
    DialogState.CLOSED,
}
