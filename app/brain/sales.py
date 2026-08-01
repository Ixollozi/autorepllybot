from __future__ import annotations

import logging
import re

from app.brain.guards import guard_client_text
from app.brain.llm import LlmError, chat_completion
from app.brain.offtopic import (
    BOT_ASK_REPLY_DISCLOSE,
    BOT_ASK_REPLY_MASK,
    OFFTOPIC_REPLY,
    asks_if_bot,
    asks_manager,
    asks_price,
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
        "Какое действие посетителя для вас главное: "
        "записаться онлайн / оставить заявку-телефон / позвонить / написать в Telegram? "
        "Это определяет структуру."
    ),
    DialogState.BRIEF_Q2: (
        "Что из этого у вас уже есть: логотип, фото работ/помещения, прайс, тексты, "
        "Instagram/2GIS/сайт? Что есть — используем."
    ),
    DialogState.BRIEF_Q3: (
        "По наполнению: достаточно главная + услуги + контакты, "
        "или нужны ещё разделы — каталог / цены / команда / акции?"
    ),
    DialogState.BRIEF_Q4: (
        "К какой дате хотели бы запуститься? "
        "(Это для планирования менеджера — в ТЗ срок сдачи не фиксируем.)"
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
    return m.group(1) if m else None


def is_tz_confirm(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(
        w in t
        for w in ("да", "верно", "всё так", "все так", "ок", "окей", "согласен", "подтверж", "yes")
    )


def build_tz_summary(brief: dict) -> str:
    return (
        "Итого, ваш проект выглядит так:\n\n"
        f"— формат: {brief.get('fork') or '—'}\n"
        f"— главное действие: {brief.get('q1') or '—'}\n"
        f"— материалы: {brief.get('q2') or '—'}\n"
        f"— разделы: {brief.get('q3') or '—'}\n\n"
        "Без оценки стоимости и сроков на этом шаге — "
        "сначала фиксируем задачу, затем менеджер пришлёт варианты.\n\n"
        "Всё верно, ничего не забыли?"
    )


ACK_NIGHT = (
    "Получили ваше сообщение — спасибо. Разберём утром в рабочее время "
    "и продолжим по задаче."
)

PRICE_BRIDGE = (
    "Чтобы назвать точную стоимость, сначала зафиксируем задачу — "
    "2–3 коротких вопроса, затем менеджер пришлёт варианты. "
    "Можем начать с формата: 1) лендинг/сайт под заявки 2) бот/автоматизация?"
)


async def polish_with_llm(
    draft: str,
    *,
    identity: str,
    user_text: str,
    state: str,
) -> str:
    system = _read_prompt("system_sales.md")
    cases = _read_prompt("cases_whitelist.md")
    identity_note = {
        "mask": "Не раскрывай, что ты ИИ, если не спросят напрямую.",
        "disclose": "Можно коротко обозначить, что это ассистент NST.",
        "disclose_on_ask": "Маскируйся, пока не спросят «ты бот?».",
    }.get(identity, "")
    messages = [
        {"role": "system", "content": f"{system}\n\nКейсы:\n{cases}\n\n{identity_note}"},
        {
            "role": "user",
            "content": (
                f"Состояние воронки: {state}\n"
                f"Сообщение клиента: {user_text}\n"
                f"Черновик ответа (можно слегка смягчить стиль, смысл сохрани):\n{draft}"
            ),
        },
    ]
    try:
        text = await chat_completion(messages, temperature=0.4, max_tokens=500)
    except LlmError:
        return draft
    ok, reason = guard_client_text(text)
    if not ok:
        logger.warning("LLM guard blocked (%s), using draft", reason)
        return draft
    return text


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
    ):
        self.reply = reply
        self.new_state = new_state
        self.brief = brief
        self.escalate = escalate
        self.escalate_reason = escalate_reason
        self.crm_events = crm_events or []
        self.assist_only = assist_only


async def handle_sales_turn(
    *,
    user_text: str,
    state: str,
    brief_raw: str | None,
    settings: dict,
    mode: str,
    niche_hint: str | None = None,
) -> SalesResult:
    brief = loads_brief(brief_raw)
    sales_depth = settings.get("sales_depth") or "full_tz"
    identity = settings.get("identity") or "mask"
    scope = settings.get("scope") or "work_only"

    if mode in ("MANUAL", "SILENT", "TAKEOVER"):
        return SalesResult(None, state, brief)

    if mode == "ACK_ONLY":
        return SalesResult(ACK_NIGHT, state, brief)

    st = DialogState(state) if state in DialogState._value2member_map_ else DialogState.NEW

    if asks_manager(user_text):
        return SalesResult(
            "Подключаю менеджера — он напишет здесь по задаче и расчёту.",
            DialogState.HUMAN_TAKEOVER.value,
            brief,
            escalate=True,
            escalate_reason="client_asked_manager",
        )

    if is_offtopic(user_text) and scope != "work_plus_smalltalk":
        return SalesResult(
            OFFTOPIC_REPLY,
            st.value,
            brief,
            escalate=True,
            escalate_reason="offtopic",
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
        )

    if asks_price(user_text) and st in (
        DialogState.NEW,
        DialogState.GREETING_QUALIFY,
        DialogState.MSG1_COMBO_SENT,
        DialogState.WAIT_FORK,
    ):
        return SalesResult(PRICE_BRIDGE, DialogState.WAIT_FORK.value, brief)

    if st in TERMINAL_BLOCK:
        return SalesResult(None, st.value, brief)

    crm_events: list[dict] = []

    # NEW / GREETING → send combo
    if st in (DialogState.NEW, DialogState.GREETING_QUALIFY):
        niche = niche_hint or detect_niche(user_text)
        brief["niche"] = niche
        combo = combo_for_niche(niche)
        if sales_depth == "ack":
            reply = "Здравствуйте! На связи NeoSampTech. Получили сообщение — менеджер подключится по задаче."
            return SalesResult(
                reply,
                DialogState.HUMAN_TAKEOVER.value,
                brief,
                escalate=True,
                escalate_reason="sales_depth_ack",
            )
        reply = await polish_with_llm(
            combo, identity=identity, user_text=user_text, state=st.value
        )
        crm_events.append({"type": "msg1_sent", "patch": {"msg1_sent": True}})
        return SalesResult(
            reply,
            DialogState.WAIT_FORK.value,
            brief,
            crm_events=crm_events,
            assist_only=(mode == "ASSIST"),
        )

    if st in (DialogState.MSG1_COMBO_SENT, DialogState.WAIT_FORK):
        fork = parse_fork(user_text)
        if not fork:
            # soft re-ask
            return SalesResult(
                "Напишите «1» или «2» — так быстрее зафиксируем формат.",
                DialogState.WAIT_FORK.value,
                brief,
                assist_only=(mode == "ASSIST"),
            )
        brief["fork"] = "landing_lead" if fork == "1" else "bot_or_site"
        crm_events.append({"type": "msg1_reply", "patch": {"msg1_reply": True}})
        nxt = next_after_fork(sales_depth)
        if nxt == DialogState.HUMAN_TAKEOVER:
            return SalesResult(
                "Отлично, формат зафиксировал. Дальше подключится менеджер с вариантами.",
                nxt.value,
                brief,
                escalate=True,
                escalate_reason="sales_depth_combo",
                crm_events=crm_events,
            )
        q = BRIEF_QUESTIONS[DialogState.BRIEF_Q1]
        return SalesResult(
            f"Отлично. {q}",
            DialogState.BRIEF_Q1.value,
            brief,
            crm_events=crm_events,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q1:
        brief["q1"] = user_text.strip()[:500]
        return SalesResult(
            f"Понял. {BRIEF_QUESTIONS[DialogState.BRIEF_Q2]}",
            DialogState.BRIEF_Q2.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    if st == DialogState.BRIEF_Q2:
        brief["q2"] = user_text.strip()[:500]
        return SalesResult(
            f"Отлично, это упрощает. {BRIEF_QUESTIONS[DialogState.BRIEF_Q3]}",
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
        return SalesResult(
            summary,
            DialogState.WAIT_TZ_CONFIRM.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    if st in (DialogState.TZ_DRAFT_SENT, DialogState.WAIT_TZ_CONFIRM):
        if is_tz_confirm(user_text):
            crm_events.append(
                {
                    "type": "tz_confirmed",
                    "note": build_tz_summary(brief),
                    "patch": {"status": "Ответил"},
                }
            )
            return SalesResult(
                "Отлично, зафиксировал. Сейчас подключится менеджер с вариантами решения.",
                DialogState.TZ_CONFIRMED.value,
                brief,
                escalate=True,
                escalate_reason="tz_confirmed",
                crm_events=crm_events,
            )
        # treat as correction → rebuild
        brief["q3"] = (brief.get("q3") or "") + f" | уточнение: {user_text.strip()[:200]}"
        summary = build_tz_summary(brief)
        return SalesResult(
            summary,
            DialogState.WAIT_TZ_CONFIRM.value,
            brief,
            assist_only=(mode == "ASSIST"),
        )

    # fallback: send combo
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
