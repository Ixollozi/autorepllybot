# NST AutoReply

Умный Telegram-автоответчик продаж для **NeoSampTech** (Ташкент / Узбекистан).

**Одной фразой:** бот подключён к рабочему TG через Business Chat Automation, отвечает от имени аккаунта, ведёт клиента до подтверждённого резюме задачи **без цены и сроков сдачи**, пишет в CRM, а владелец управляет через **пульт Mini App**.

| Документ | Роль |
|----------|------|
| **Этот README** | Единый источник правды: продукт + аудит + запуск |
| [`BACKLOG.md`](BACKLOG.md) | Живой чеклист задач (не дублировать сюда статусы галочек) |
| [`prompts/`](prompts/) | Тексты Combo / humanize / кейсы |

Устаревшие разнесённые черновики (`TZ.md`, `MINIAPP.md`, `DEPLOY.md`) сведены сюда; при расхождении — **этот файл** + актуальный код.

---

## 0. Аудит (актуально на 2026-08-02)

### Вердикт

Каркас рабочий: Business → воронка → CRM → пульт.  
Главный риск не «некрасивый UI», а **дыры конверсии и рассинхрон состояний**: ASSIST двигает воронку без ответа клиенту, resume после takeover ведёт себя по-разному, Msg1 без 2 кейсов из скрипта, CRM lookup по TG не используется.

**KPI бота:** вилка → бриф → эскалация менеджеру → WIN. Не «умный чат».

### Что работает хорошо

- Business API без Telethon; ответ через `business_connection_id`
- Пульт `/mini_app`: режимы, пресеты, диалоги, takeover/resume, очистка переписки
- Settings SoT в CRM; бот pull ~45с + очередь действий (takeover/resume/wipe)
- Loop-guard (не долбить Combo на «привет»), guards (цена / срок / чужой алфавит)
- STT: Groq Whisper → local faster-whisper; голосовые в inbox
- Детект ручного ответа владельца → takeover; hostile → короткая эскалация
- Nurture follow-up на «зависших» шагах; лимит ~100 сообщений на чат в CRM

### Доработать (P0 — сначала)

| # | Проблема | Зачем |
|---|----------|--------|
| 1 | **ASSIST двигает state/CRM без отправки клиенту** | Воронка «пройдена», клиент молчит → ложь в CRM |
| 2 | **Resume рассинхрон:** inbox → `NURTURE` (потом снова Combo); Mini App → `WAIT_FORK`/`ACTIVE` | Повтор Msg1, сброс прогресса |
| 3 | **Msg1 без 2 кейсов whitelist** в Combo | Скрипт NST требует боль + 2 кейса + вилка |
| 4 | **Нет CRM `lookup` по Telegram** при первом касании | Дубли лидов, теряется ветка/скор с обзвона |
| 5 | **`is_tz_confirm`:** substring «да» ловит «дата»/«задача» | Ложное подтверждение ТЗ |
| 6 | **`on_business_connection`:** сессия/права пишутся криво | `business_ok` / takeover ломаются |
| 7 | **Нет singleton lock** | Два `app.main` = двойные ответы |
| 8 | **Nurture игнорирует ASSIST/MANUAL** | Follow-up клиенту, когда «бот не отвечает» |
| 9 | **Heartbeat «онлайн»:** пульт 180с vs Связь 900с | Противоречивый статус |
| 10 | **Эскалация на каждый offtopic/bot-ask** | Спам inbox |

### Добавить (P1)

- Msg1 = нишевая боль + **2 кейса** + вилка 1/2 (dental/retail/edu)
- Чтение `script_branch` / `script_score` / `script_offer` с лида → глубина воронки
- Возражения («дорого», «сами», «не ЛПР») — не писать в слоты брифа
- Цена mid-brief → price-bridge, не `q1`
- Post-TZ: короткий expect-manager + nurture по скрипту
- UI nurture + identity + редактор ignore-list в пульте
- `DELETE` диалога целиком; restore `pre_takeover_state` при resume
- Enforce `max_out_per_chat_hour`; STT fail → алерт владельцу
- M3: ASSIST approve/discard в пульте (и только тогда двигать state)

### Добавить (P2)

- UZ-first / language mirror; KPI drop-off Msg1→fork→TZ→WIN
- Intent из свободного текста → автозаполнение брифа
- A/B Msg1; 👍/👎 оператора; multi-op (M4)
- Weekly digest за период, не all-time

### Удалить / упростить

| Убрать | Почему |
|--------|--------|
| Inbox resume → `NURTURE` | Мёртвое состояние → повтор Combo |
| Штамп `msg2_sent=True` вместе с Msg1 | Ложь под скрипт |
| Эскалация на каждый offtopic / «ты бот?» | Достаточно локального ответа; escalate по streak/hostile |
| Humanize на коротких canned-шагах (после эскалации/вилки) | Порча текста, стоимость LLM |
| Мёртвые knobs без кода: `escalation` paranoid/late, `language` uz/mirror | Или внедрить, или убрать из UI |
| Dead SM: `OBJECTION_HANDLING` (не входит) | Или реализовать, или выпилить |
| Дубль режимов Home + Настройки | Оставить один явный блок |
| Развивать ASSIST «в бою» до M3 | В бою по умолчанию только **AUTO** |
| Полный CRM внутри Mini App / kanban | Не дублировать CRM |

---

## 1. Проблема и KPI

| Симптом | Цена |
|---------|------|
| Ответ через часы | «Уже нашли других» |
| Голосовые не читаются | Пропуск смысла |
| «Скиньте в TG» без discovery | Нет брифа → нет КП |
| Всё руками владельца | Не масштабируется |

**KPI продукта**

1. Time-to-first-reply ≤ 60 сек (день) / ≤ 2 мин (ночь, если AUTO)
2. % диалогов с ≥2 слотами брифа
3. % с подтверждённым резюме ТЗ
4. % вовремя эскалированных (бот не «варит» цену сам)
5. Качество лида до человека (≤10 мин на КП вместо 40 на допрос)

**Не KPI:** «звучит умно», длина промпта, число сообщений бота.

### Бот сознательно НЕ делает

- Цены, пакеты, скидки, предоплата  
- Обещания сроков сдачи («за 7 дней»)  
- Договор / оплату  
- Выдуманные кейсы  
- Ответы в чатах с takeover / MANUAL  

Клиент *может* назвать желаемый запуск в брифе — в резюме ТЗ **дата сдачи не пишется**.

---

## 2. Архитектура

```
Клиент DM (рабочий аккаунт)
    → Telegram Business updates
        → Автоответчик (polling)
            → handlers_business  — клиент, STT, sales, CRM
            → handlers_owner     — inbox, takeover, /start claim
            → brain/*            — воронка, humanize, nurture, guards
            → CRM API            — NSTLeadGen /api/integrations/autoreply
        → Пульт Mini App         — crm.neosamptech.uz/mini_app
        → Owner inbox            — STT + «нужен человек»
```

| Поверхность | Задачи |
|-------------|--------|
| **Mini App** | Режимы, пресеты, диалоги, takeover, связь CRM↔бот |
| **Личка с ботом** | Inbox (голос, эскалации), кнопки «Взять / Бот снова / Пульт» |
| **CRM /settings** | Пулы Groq/Gemini, API-ключ AutoReply |
| **CRM /leads** | Карточка лида, Msg1 flags, comment, tasks |

**Почему не Telethon:** официальный Business API, ниже риск бана, один процесс.

---

## 3. Воронка продаж (как должно быть)

Якорь: скрипт NST в CRM (`/script-prodazh.html`) — TG-first, Msg1 ≤60 мин.

```
NEW → Msg1-Combo (боль + 2 кейса + вилка 1/2)
    → WAIT_FORK
    → BRIEF_Q1…Q4 (мини-бриф)
    → WAIT_TZ_CONFIRM (резюме без цены/срока сдачи)
    → TZ_CONFIRMED → эскалация менеджеру
```

| Шаг | Поведение |
|-----|-----------|
| Вилка | `1` сайт/лендинг · `2` бот; или своими словами |
| Цена рано | Bridge → «сначала задача», без цифр |
| Hostile / «менеджер» | Короткая передача человеку |
| «Ты бот?» | mask / disclose по настройке identity |
| Takeover | Владелец пишет сам → бот молчит 4ч (или кнопка) |

**CRM-поля (цель):** `script_branch`, `script_score`, `script_offer`, `msg1_*`, comment, touches/tasks на событиях.

---

## 4. Пульт Mini App

**URL:** https://crm.neosamptech.uz/mini_app  
**Вход:** только Telegram `initData` (не CRM cookie).

| Вкладка | Содержание |
|---------|------------|
| **Пульт** | Статус «бот отвечает?», быстрый режим, пресеты, STT/CRM sync |
| **Настройки** | Ночь, глубина, скорость; подсказки «?» |
| **Диалоги** | Список, тред, takeover/resume, очистка переписки |
| **Связь** | Claim-код → `/start c_…` у бота, heartbeat, Business |

**Пресеты**

| Имя | Смысл |
|-----|--------|
| Боевой | AUTO · полный бриф · nurture active |
| Осторожный | ASSIST · короче · строже |
| Секретарь | Короткий ack · disclose |
| Ночной | Ночью ack · днём combo |

**Хранение переписки:** до ~100 последних текстовых сообщений на чат в CRM (килобайты). Очистка в пульте ≠ удаление у клиента в Telegram.

**Очередь к боту:** `pending_dialog_actions` (takeover / resume / wipe) — бот забирает на inbound и раз в ~45с.

---

## 5. Напоминания (nurture)

Не «будильник в UI», а фоновый follow-up:

| | soft (дефолт) | active |
|--|---------------|--------|
| Тишина клиента | ≥ 4 ч | ≥ 3 ч |
| Макс. штук | 2 | 3 |
| Пауза между | ≥ 20 ч | ≥ 20 ч |

Шлёт только на шагах: вилка / бриф / «подтвердите резюме».  
**Не шлёт** при takeover / pause / nurture=off.  
*(Должно также не слать в ASSIST/MANUAL — см. аудит P0.)*

---

## 6. Режимы и ночь

| Режим | Клиенту |
|-------|---------|
| **AUTO** | Бот отвечает сам (боевой дефолт) |
| **ASSIST** | Черновик только владельцу *(пока M3 не готов — не использовать в бою)* |
| **MANUAL** | Тишина |

| Ночь | Поведение |
|------|-----------|
| Как днём | Полный AUTO |
| Только «принято» | Короткий ack |
| Молчит | Без ответа |
| Черновики | Как ASSIST ночью |

Tempo: сразу / как человек (~2–4с) / медленно.

---

## 7. Guards (жёстко)

Исходящее клиенту **блокируется**, если есть:

- цена / прайс / оплата / суммы  
- обещание срока сдачи  
- иероглифы / чужой алфавит (защита от порчи LLM)

Humanize (LLM) переписывает черновик «по-человечески»; на canned-ответах (бот?, hostile, эскалация) — **без LLM**.

---

## 8. Быстрый старт

### 8.1. Telegram

1. BotFather → **Business / Secretary Mode = On**  
2. Рабочий аккаунт (Premium/Business) → Settings → Business → Chatbots → бот + **Reply**  
3. Menu Button → `https://crm.neosamptech.uz/mini_app`

### 8.2. CRM

1. В CRM Settings → AutoReply API-ключ (или `.env` `AUTOREPLY_API_KEY`)  
2. Пулы Groq (и опционально Gemini) в Settings → AI  
3. Frontend route `/mini_app` задеплоен вместе с CRM

### 8.3. Бот (локально / VPS)

```bash
cd Автоответчик
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # заполнить
mkdir -p data logs
# ffmpeg в PATH для голосовых
python -m app.main
```

`.env` (минимум):

```env
BOT_TOKEN=
OWNER_CHAT_ID=
CRM_BASE_URL=https://crm.neosamptech.uz
AUTOREPLY_API_KEY=
MINIAPP_URL=https://crm.neosamptech.uz/mini_app
TZ=Asia/Tashkent
```

Ключ можно не класть в `.env`: Пульт → **Связь** → «Подключить бота» → `/start c_…`.

Опциональный fallback LLM без CRM: `GROQ_API_KEY` / `GEMINI_API_KEY`.

### 8.4. Docker / systemd

```bash
docker compose up -d --build
```

Unit: [`deploy/nst-autoreply.service`](deploy/nst-autoreply.service).

**Важно:** один процесс polling. Два `app.main` = двойные ответы.

### 8.5. Тесты

```bash
pytest -q
```

---

## 9. Деплой CRM (integration)

На VPS `crm.neosamptech.uz`:

```bash
# после git pull
bash deploy/deploy.sh
# или: docker compose -f docker-compose.prod.yml up -d --build
```

Проверка:

```bash
curl -s -H "X-API-Key: $AUTOREPLY_API_KEY" \
  https://crm.neosamptech.uz/api/integrations/autoreply/llm-keys
```

---

## 10. Чеклист приёмки

- [ ] Business message → inbox ≤ 5 сек  
- [ ] Ответ клиенту через `business_connection_id`  
- [ ] Голос + расшифровка в inbox  
- [ ] Ручной ответ владельца → takeover (бот молчит)  
- [ ] Combo → вилка → бриф → ТЗ без цены  
- [ ] Guards ловят цену / сроки  
- [ ] CRM: лид, comment, script fields, события  
- [ ] Пульт: AUTO, статус онлайн, takeover/resume  
- [ ] Один процесс бота, режим **AUTO** в бою  

---

## 11. Структура репозитория

```
Автоответчик/
  app/
    main.py              # polling + loops
    bot/                 # handlers, keyboards, settings_store, labels
    brain/               # sales, humanize, loop_guard, nurture, offtopic, guards
    crm/client.py
    stt/whisper_stt.py
    db/models.py         # SQLite
  prompts/               # Combo × ниша, system_sales, cases_whitelist
  deploy/
  BACKLOG.md             # очередь задач
  README.md              # этот файл
```

Пульт и CRM API: репозиторий **NSTLeadGen**  
`frontend/src/pages/mini_app/` · `backend/app/api/integrations_autoreply*.py`

---

## 12. Очередь работ (сжато)

См. детали в [`BACKLOG.md`](BACKLOG.md).

1. P0 конверсия: ASSIST/state, resume, Msg1+кейсы, lookup, tz_confirm, business_connection, singleton  
2. P1 скрипт: branch/score, objections, nurture UI, max_out, M3 drafts  
3. P2: UZ, KPI dashboard, multi-op  

**Сейчас в бою:** режим **AUTO**, один процесс бота, пульт для takeover/resume, не полагаться на ASSIST.
