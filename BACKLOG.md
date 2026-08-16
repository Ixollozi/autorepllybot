# AutoReply — backlog (не потерять)

**Единый обзор продукта + аудит:** [`README.md`](README.md)  
**Дата фиксации:** 2026-08-01 · обновлено: 2026-08-02 (полный аудит → README §0)  
**Источник:** код + обсуждение + скрипт CRM [`/script-prodazh.html`](https://crm.neosamptech.uz/script-prodazh.html)  
**Статус кода:** runtime 0–2 + пульт M0–M2; **M3 ASSIST approve** открыт.  
**Единственный KPI бота:** вилка → бриф → эскалация → WIN.

Читать этот файл + `MINIAPP.md` + якоря скрипта (§G0) перед новой итерацией.

---

## 0. Стратегия UX (новое)

- **Не развивать** сложные inline-настройки в чате бота.
- **Цель:** Mini App на `https://crm.neosamptech.uz/mini_app` — режимы, пресеты, диалоги, ASSIST approve.
- Бот в TG = inbox + алерты + кнопка «Открыть пульт».
- Детали: [`MINIAPP.md`](MINIAPP.md).

### Mini App roadmap
- [x] **M0** Shell `/mini_app` + initData auth + Menu Button
- [x] **M1** Settings + пресеты (SoT в CRM, бот pull)
- [x] **M2** Диалоги + takeover из Mini App (read-model + actions; sync с бота)
- [ ] **M3** ASSIST drafts approve/discard
- [ ] **M4** Deep links из алертов, stats, multi-op

---

## G. Продажи и конверсия (приоритет №1)

Источник правды по смыслу: **рабочий скрипт NST v9.1/v10** в CRM (`script-prodazh.html` + поля `script_branch` / `script_score` / `script_offer` / Msg1*).  
Бот = исполнение TG-части скрипта после интереса / «скиньте в TG», **не** замена холодного звонка.

### G0. Якоря скрипта (бот обязан соблюдать)

| Якорь скрипта | Как должен вести себя бот |
|---------------|---------------------------|
| TG-first · Msg1 ≤60 мин | Combo уходит быстро; не «ответим завтра» без политики ночи |
| Msg1 = боль/гипотеза ниши + **2 кейса** + вилка «1/2» | Сейчас кейсы в Combo часто пустые — закрыть |
| Голые ссылки без вопроса = провал | Всегда вилка или один следующий шаг в том же сообщении |
| Лестница: вилка → мини-бриф → резюме ТЗ → человек/КП | Не прыгать на «созвон» / цену |
| Цена / срок сдачи — менеджер | Бот не называет; bridge → бриф |
| Ветка S/W/P/D/N + скор A–D | Писать в CRM; глубина воронки бота зависит от score |
| После «да» на ТЗ | Не ghost: эскалация + короткий expect-manager текст |
| Follow-up | +4–12ч переспрос вилки · +24ч новая деталь ниши · не «ну как?» |

### G1. Привязка к скрипту CRM — сделать

- [ ] **Script engine v1:** читать с лида (lookup) `script_branch`, `script_score`, `script_offer`, нишу → выбирать Combo / глубину / nudge
- [ ] **Скор A–D → поведение:** A = полный бриф+приоритет эскалации; B = обычная цепочка; C = короткий Combo; D = Msg1 + мягкий выход без тяжёлого брифа
- [ ] **Ветка S/W/P/D/N → оффер и боль** в Msg1 (S: нет сайта; W: слабый поток; P: осторожно / эскалация; D/N: выход)
- [ ] **Msg1-Combo как в скрипте:** нишевая гипотеза + **2 кейса из whitelist** + вилка 1/2 в одном сообщении
- [ ] **Нишевые вилки** (стомат/ритейл/edu), не один generic 1/2 на всех
- [ ] **CRM lookup по Telegram** при первом касании — не плодить дубли, подтянуть ветку/скор с обзвона
- [ ] Маппинг статусов: Msg1 → `Написал`; ответ на вилку → `Ответил`; ТЗ confirm → эскалация + note; WIN/LOSS только человек
- [x] Поля CRM: `msg1_sent`, `msg1_reply`, `script_offer`, comment-сводка, timing-signal — стабильно и без спама notes
- [x] **Ветка/скор/касания/задачи:** автоответчик пишет `script_branch`/`script_score`, создаёт touches и tasks на событиях (2026-08-01)
- [ ] Возражения по скрипту («дорого», «сами», «не ЛПР», «бесплатно») → ветка objection / DISQUALIFIED / HUMAN, не запись в q1
- [ ] Цена mid-brief: «сколько стоит?» → price-bridge, **не** слот брифа
- [ ] Post-TZ: expect-manager + nurture «когда ответите?» по скрипту, не terminal silence
- [ ] Follow-up nurture: тексты как в скрипте (новая деталь ниши), не «ну как?»

### G2. Конверсия — быстрые фиксы логики (аудит 2026-08-01)

- [ ] **ASSIST не двигает state**, пока черновик не approve (или пока не M3) — иначе клиент молчит, воронка «пройдена»
- [ ] Жёстче `is_tz_confirm` (только явное «да/верно/всё так», не substring в «дата»)
- [ ] Resume после takeover → вернуть **предыдущий sales state**, не `NURTURE` → повтор Combo
- [ ] После TZ confirm — короткий ответ клиенту + escalate (не ghost)
- [ ] Price/objection handlers на стадиях BRIEF_Q*
- [ ] STT fail / пустой транскрипт → escalate владельцу, не тишина
- [ ] Business connection persist в БД (takeover / heartbeat)
- [ ] PID/singleton lock — один polling-процесс
- [ ] `max_out_per_chat_hour` реально резать исходящие
- [ ] OWNER_CHAT_ID автосохранение при `/start`

### G3. Конверсия — средний слой

- [ ] Intent из свободного текста (сайт+запись, конкурент, срочность) → brief + fork
- [ ] Dead states оживить или выкинуть: `OBJECTION_HANDLING`, согласовать `TZ_DRAFT_SENT` / `MSG1_COMBO_SENT`
- [ ] `sales_depth` согласовать с score: brief ≠ «забыли ТЗ»; full_tz только для A/B
- [ ] UZ-first зеркало Combo / STT language
- [ ] Humanize: быстрее на коротких шагах; CTA 1/2 всегда сохранять (уже есть guard — расширить на бриф-вопросы)
- [ ] Nurture personalization по niche/q1; не слать в ASSIST/MANUAL
- [ ] Pause/takeover/resume dual-write в CRM SoT (Mini App не stale)
- [ ] KPI-события: `fork_answered`, `brief_slot_filled`, `tz_sent`, `tz_confirmed` + weekly digest за период, не all-time

### G4. Конверсия — продукт / позже

- [ ] **M3** ASSIST approve/edit → send через `business_connection_id`
- [ ] A/B Msg1 / вилок по нише
- [ ] Оценка качества ответа (👍/👎 оператора) → обучение промптов
- [ ] Drop-off дашборд: Msg1 → fork → brief → TZ → escalate → WIN
- [ ] Multi-op / роли → **M4**

---

## A. Ops (блокер запуска на проде)

- [x] Задеплоить NSTLeadGen с `/api/integrations/autoreply` + UI ключа AutoReply на `https://crm.neosamptech.uz` *(прод жив; уточнять при регрессе)*
- [x] CRM ↔ бот ключ через Mini App «Связь» / SQLite *(локально работает; .env ключ опционален)*
- [ ] Проверить `/status` в боте (Groq/Gemini keys > 0) на каждом подъёме
- [ ] BotFather: Business / Secretary Mode = On
- [ ] Рабочий аккаунт: Business → Chatbots → бот + право Reply
- [ ] Поднять бота на VPS (ffmpeg + Whisper) — сейчас часто локально
- [ ] Живая приёмка по чеклисту TZ §16
- [ ] Режим по умолчанию для боя: **AUTO** (ASSIST только для отладки черновиков)

См. также [`DEPLOY.md`](DEPLOY.md).

**Локальный демо-путь LLM без CRM API:** `GROQ_API_KEY` / `GEMINI_API_KEY` в `.env` бота (fallback).

---

## B. Дырки v1 → закрываются через Mini App M1–M3

Не пилить дальше в inline TG (кроме ссылки на Mini App):

- [ ] ASSIST approve UI → **M3** (+ не двигать state до approve — §G2)
- [x] Пресеты → **M1**
- [x] work_hours / ignore_list UI → **M1**
- [ ] OWNER_CHAT_ID автосохранение — мелкий фикс бота
- [x] `/mode` — в Mini App
- [x] Inbox-фильтры / диалоги → **M2**

---

## C. v1.5 (отложено / частично в Mini App)

- [ ] ASSIST approve UX целиком → **M3**
- [ ] Stop-words UI → M1/M2
- [ ] Niches toggles → M1
- [ ] Takeover edge cases Business updates
- [ ] Voice/audio STT cloud fallback (если local fail)

---

## D. v2 / уровень C (отложено)

- [ ] UZ-first ветка
- [ ] A/B Msg1 / вилок
- [ ] Оценка качества ответов
- [ ] Веб-админка настроек (частично = Mini App + CRM settings)
- [ ] CRM как LLM-proxy
- [ ] Мультиоператор / роли → **M4**

---

## E. Уже сделано (якорь)

- CRM: integration API + UI генерации Autoreply API key + Mini App M0–M2
- Бот: Business inbox + STT + takeover + sales funnel + CRM sync + `/crm_key`/`/crm_url`
- Loop-guard (не спамить Combo на каждый «привет»)
- Humanize слой (контекст + TG-стиль) + guard CTA 1/2
- CRM brief comment / script_offer / dedupe timing notes
- Docs: TZ, DEPLOY, BACKLOG, **MINIAPP**

---

## F. Решения-якоря

| Тема | Решение |
|------|---------|
| UX управления | **Telegram Mini App в CRM `/mini_app`** |
| Settings SoT | CRM (после M1); бот — cache/pull |
| Скрипт продаж SoT | CRM `script-prodazh.html` + поля лида; бот исполняет TG-лестницу |
| KPI | Вилка → бриф → ТЗ → менеджер → выручка |
| Идентичность | mask; work-only |
| Аккаунт | рабочий + Chat Automation |
| STT | local faster-whisper |
| LLM | ключи из CRM; Groq → Gemini |
| Цена/срок сдачи | бот не называет |

---

## H. Очередь внедрения (чтобы не распыляться)

**Сейчас (конверсия):**
1. ASSIST не двигает state / или переключить бой на AUTO  
2. Msg1 = 2 кейса + нишевая вилка по скрипту  
3. Lookup лида + branch/score → глубина  
4. TZ confirm + post-TZ + price/objection mid-brief  
5. Resume ≠ Combo; STT fail → escalate  

**Потом:** M3 approve · nurture по скрипту · KPI drop-off · UZ · A/B  
