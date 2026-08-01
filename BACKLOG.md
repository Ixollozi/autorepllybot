# AutoReply — backlog (не потерять)

**Дата фиксации:** 2026-08-01  
**Источник:** обсуждение + [`TZ.md`](TZ.md) + план реализации  
**Статус кода:** фазы 0–2 в репозитории реализованы; ниже — ops, дырки v1 и отложенное.

Читать этот файл перед любой новой итерацией по автоответчику.

---

## A. Ops (блокер запуска на проде)

- [ ] Задеплоить NSTLeadGen с `/api/integrations/autoreply` на `https://crm.neosamptech.uz`
- [ ] Прописать `AUTOREPLY_API_KEY` в `.env` CRM (и тот же ключ у бота)
- [ ] Проверить `GET /api/integrations/autoreply/llm-keys` с ключом
- [ ] Убедиться, что в CRM Настройки → AI есть ключи Groq (и Gemini как fallback)
- [ ] BotFather: Business / Secretary Mode = On
- [ ] Рабочий аккаунт: Business → Chatbots → бот + право Reply
- [ ] Заполнить `.env` бота: `BOT_TOKEN`, `OWNER_CHAT_ID`, `CRM_BASE_URL`, `AUTOREPLY_API_KEY`
- [ ] Поднять бота (systemd / docker), ffmpeg + Whisper на VPS
- [ ] Owner: `/start` → `/settings`
- [ ] Живая приёмка по чеклисту TZ §16 (голос, ответ от аккаунта, takeover, ТЗ без цены, CRM sync)

См. также [`DEPLOY.md`](DEPLOY.md).

---

## B. Дырки v1 (обсуждали / в ТЗ must, в UI или UX ещё нет)

- [ ] **ASSIST approve:** кнопка «✅ Отправить» у черновика (сейчас только показ черновика в inbox)
- [ ] **Пресеты** одним тапом: Боевой / Осторожный / Только секретарь / Ночной дежурный (TZ §11.3)
- [ ] **`work_hours`** редактировать из `/settings` (сейчас только дефолт в БД)
- [ ] **`ignore_list`** управлять из `/settings` (сейчас поле есть, UI нет)
- [ ] **`OWNER_CHAT_ID`:** автосохранение при первом `/start`, если env пустой (сейчас только лог)
- [ ] Команда **`/mode`** (в DoD TZ §16; сейчас только cycle в `/settings`)
- [ ] Inbox-фильтры (все / только голос / только если бот ответил) — частично в ТЗ §11.2 п.8

---

## C. v1.5 (отложено сознательно)

- [ ] ASSIST approve UX целиком (approve / edit / discard)
- [ ] Stop-words UI → сразу HUMAN
- [ ] Niches toggles (dental / retail / edu / generic on/off)
- [ ] Inbox filters UI
- [ ] Уточнение takeover на всех типах Business updates (edited / outgoing edge cases)

---

## D. v2 / уровень C (отложено)

- [ ] UZ-first ветка (Combo + бриф на узбекском как first-class)
- [ ] A/B Msg1 / вилок
- [ ] Оценка качества ответов
- [ ] Веб-админка настроек
- [ ] CRM как LLM-proxy (`POST /api/integrations/llm/chat`) — ключи не уходят боту
- [ ] Мультиоператор / роли
- [ ] Per-operator профили

---

## E. Уже сделано (якорь, не переделывать зря)

- CRM: `AUTOREPLY_API_KEY`, `/api/integrations/autoreply/*` (llm-keys, lookup, upsert, patch, notes, events)
- CRM: пулы Groq + Gemini в UI/API (были до автоответчика)
- Бот: Business inbox + STT + takeover/pause + settings cycle
- Бот: воронка Combo → бриф → ТЗ без цены/сроков сдачи
- Бот: guards цена/дедлайн, оффтоп, nurture, weekly digest, CRM sync событий
- Тесты: CRM integration + guards/offtopic/state_machine
- Доки: `TZ.md`, `README.md`, `DEPLOY.md`, docker/systemd

---

## F. Решения-якоря (не переспрашивать без причины)

| Тема | Решение |
|------|---------|
| Идентичность | mask по умолчанию; work-only; оффтоп → отказ + эскалация |
| Аккаунт | рабочий + Chat Automation, без Telethon |
| STT | local faster-whisper (бесплатно) |
| LLM | ключи из CRM; Groq → Gemini |
| Ночь | дефолт full_auto, переключается в settings |
| Q4 срок запуска | в CRM/note, не в клиентское резюме ТЗ |
| Цена/срок сдачи | бот никогда не называет |
| CRM sync | с v1 через X-API-Key |

При смене якоря — обновить этот файл и §0.1 в `TZ.md`.
