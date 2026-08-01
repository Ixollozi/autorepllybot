# AutoReply — backlog (не потерять)

**Дата фиксации:** 2026-08-01 · обновлено: Mini App как целевой UX  
**Источник:** обсуждение + [`TZ.md`](TZ.md) + [`MINIAPP.md`](MINIAPP.md)  
**Статус кода:** фазы 0–2 runtime в репо; **пульт управления → Telegram Mini App в CRM** (`/mini_app`).

Читать этот файл + `MINIAPP.md` перед новой итерацией.

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

## A. Ops (блокер запуска на проде)

- [ ] Задеплоить NSTLeadGen с `/api/integrations/autoreply` + UI ключа AutoReply на `https://crm.neosamptech.uz`
- [ ] В CRM Настройки → **AutoReply · API-ключ** → Сгенерировать → скопировать
- [ ] В боте: `/crm_url https://crm.neosamptech.uz` и `/crm_key ВАШ_КЛЮЧ` (или `.env`)
- [ ] Проверить `/status` в боте (Groq/Gemini keys > 0)
- [ ] BotFather: Business / Secretary Mode = On
- [ ] Рабочий аккаунт: Business → Chatbots → бот + право Reply
- [ ] Поднять бота на VPS (ffmpeg + Whisper)
- [ ] Живая приёмка по чеклисту TZ §16

См. также [`DEPLOY.md`](DEPLOY.md).

**Локальный демо-путь LLM без CRM API:** `GROQ_API_KEY` / `GEMINI_API_KEY` в `.env` бота (fallback).

---

## B. Дырки v1 → закрываются через Mini App M1–M3

Не пилить дальше в inline TG (кроме ссылки на Mini App):

- [ ] ASSIST approve UI → **M3**
- [ ] Пресеты → **M1**
- [ ] work_hours / ignore_list UI → **M1**
- [ ] OWNER_CHAT_ID автосохранение — мелкий фикс бота (можно до Mini App)
- [ ] `/mode` — заменить пунктом в Mini App + deep link
- [ ] Inbox-фильтры → **M2**

---

## C. v1.5 (отложено / частично в Mini App)

- [ ] ASSIST approve UX целиком → **M3**
- [ ] Stop-words UI → M1/M2
- [ ] Niches toggles → M1
- [ ] Inbox filters → M2
- [ ] Takeover edge cases Business updates

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

- CRM: integration API + UI генерации Autoreply API key (локально)
- Бот: Business inbox + STT + takeover + sales funnel + CRM sync + `/crm_key`/`/crm_url`
- Docs: TZ, DEPLOY, BACKLOG, **MINIAPP**

---

## F. Решения-якоря

| Тема | Решение |
|------|---------|
| UX управления | **Telegram Mini App в CRM `/mini_app`** |
| Settings SoT | CRM (после M1); бот — cache/pull |
| Идентичность | mask; work-only |
| Аккаунт | рабочий + Chat Automation |
| STT | local faster-whisper |
| LLM | ключи из CRM; Groq → Gemini |
| Цена/срок сдачи | бот не называет |
