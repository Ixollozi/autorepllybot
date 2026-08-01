# Деплой NST AutoReply + CRM integration

## 1. CRM (обязательно первым)

На VPS с `https://crm.neosamptech.uz`:

1. Задеплоить обновлённый NSTLeadGen (есть роутер `/api/integrations/autoreply`).
2. В `.env` CRM добавить:

```
AUTOREPLY_API_KEY=<длинный secrets.token_urlsafe(32)>
```

3. Перезапуск compose:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

4. Проверка:

```bash
curl -s -H "X-API-Key: $AUTOREPLY_API_KEY" \
  https://crm.neosamptech.uz/api/integrations/autoreply/llm-keys | head
```

В Настройках CRM должны быть ключи Groq (и при желании Gemini).

## 2. Бот

1. BotFather → Business/Secretary Mode = On.
2. Рабочий Premium-аккаунт → Business → Chatbots → `@bot` + Reply.
3. На VPS (≥2 vCPU, ffmpeg):

```bash
git clone / copy Автоответчик → /opt/nst-autoreply
cd /opt/nst-autoreply
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить BOT_TOKEN, OWNER_CHAT_ID, CRM_BASE_URL, AUTOREPLY_API_KEY
mkdir -p data logs
cp deploy/nst-autoreply.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nst-autoreply
```

Или `docker compose up -d --build`.

4. Написать боту `/start` с owner-аккаунта → `/settings` → пресет боевой.

## 3. Приёмка (TZ §16)

См. чеклист в README.md.
