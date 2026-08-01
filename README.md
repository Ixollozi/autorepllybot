# NST AutoReply

Умный Telegram-автоответчик продаж для NeoSampTech (по [`TZ.md`](TZ.md)).

**Остаток задач / отложенное:** [`BACKLOG.md`](BACKLOG.md) — читать перед новой итерацией.

## Возможности

- Telegram **Business / Chat Automation** (без Telethon): ответы от рабочего аккаунта
- Inbox владельцу + **локальная транскрибация** (faster-whisper)
- Воронка до **ТЗ без цены и сроков сдачи**
- Режимы и политики через `/settings`
- CRM sync + LLM-ключи из **NSTLeadGen** (`/api/integrations/autoreply`)

## Быстрый старт

1. BotFather → включить **Business / Secretary Mode** у бота.
2. Рабочий аккаунт → Settings → Business → Chatbots → подключить бота (Reply).
3. Скопировать `.env.example` → `.env`, заполнить:

```env
BOT_TOKEN=...
OWNER_CHAT_ID=...   # ваш личный chat id с ботом (после /start можно взять из логов)
CRM_BASE_URL=https://crm.neosamptech.uz
AUTOREPLY_API_KEY=...  # тот же ключ, что в CRM
```

4. В CRM `.env` на проде:

```env
AUTOREPLY_API_KEY=...
```

5. Установка:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# нужен ffmpeg в PATH для голосовых
python -m app.main
```

6. Напишите боту `/start` из owner-аккаунта → `/settings`.

## Docker

```bash
docker compose up -d --build
```

## Systemd

См. [`deploy/nst-autoreply.service`](deploy/nst-autoreply.service).

## Тесты

```bash
pytest -q
```

## Чеклист приёмки (TZ §16)

- [ ] Business message → inbox ≤5 сек
- [ ] Ответ клиенту через `business_connection_id`
- [ ] Голос + расшифровка
- [ ] Takeover при ручном ответе
- [ ] Combo → бриф → ТЗ без цены
- [ ] Guards ловят цену/сроки
- [ ] CRM: msg1 / notes / qualification_json
- [ ] Ключи LLM только из CRM

## Деплой CRM (фаза 0)

На VPS CRM после обновления кода:

```bash
# добавить AUTOREPLY_API_KEY в .env
docker compose -f docker-compose.prod.yml up -d --build
```

Проверка:

```bash
curl -s -H "X-API-Key: $AUTOREPLY_API_KEY" \
  https://crm.neosamptech.uz/api/integrations/autoreply/llm-keys
```
