# Claude Telegram Bot

Мини-бот в Telegram для общения с Claude (Anthropic) с переключением между моделями.

## Возможности

- Диалог с Claude с памятью в рамках чата
- Переключение моделей через инлайн-кнопки (`/model`):
  - Opus 4.8 — самый умный (по умолчанию)
  - Sonnet 5 — баланс цены и качества
  - Sonnet 4.6 — предыдущий Sonnet
  - Haiku 4.5 — самый быстрый и дешёвый
- `/new` — очистить историю диалога
- Длинные ответы автоматически разбиваются на несколько сообщений

## Запуск

```bash
cd claude-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# впишите в .env свои TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY

python bot.py
```

Бот работает через long polling — публичный адрес и вебхуки не нужны, достаточно любого сервера или даже домашнего компьютера.

## Безопасность

- Ключи хранятся только в `.env`, который добавлен в `.gitignore` и не попадает в git.
- Если ключ засветился где-то публично — сразу перевыпустите его:
  - Anthropic: https://platform.claude.com/ → API Keys
  - Telegram: @BotFather → `/revoke`
- История диалогов хранится в памяти процесса и пропадает при перезапуске (по желанию можно добавить БД).
