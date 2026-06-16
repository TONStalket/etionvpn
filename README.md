# Claude Telegram Bot

A small Telegram bot that lets you chat with [Claude](https://www.anthropic.com/)
and switch between models on the fly (Opus 4.8 / Sonnet 4.6 / Haiku 4.5).

## Features

- 💬 Multi-turn chat with per-chat conversation memory
- 🔀 Switch models live with `/model` (inline buttons)
- ⭐️ **Subscriptions**: free plan = 10 requests on Haiku 4.5; subscribers get
  all models (Opus 4.8 / Sonnet 4.6 / Haiku 4.5) without limits
- 💳 Paid via **Telegram Stars** (no card / external provider) or granted by an admin
- 📋 **Command menu**: commands appear when you type `/` and the menu button
  shows the command list
- 🔐 Optional allowlist of Telegram user IDs
- 🔒 Secrets kept in `.env` (never committed)

## Setup

1. **Install dependencies** (Python 3.10+):

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure secrets:**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and fill in:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `ANTHROPIC_API_KEY` — from the [Anthropic Console](https://console.anthropic.com/)
   - `ALLOWED_USER_IDS` *(optional)* — comma-separated Telegram user IDs; leave
     empty to allow anyone.

3. **Run it:**

   ```bash
   python bot.py
   ```

## Commands

| Command       | Description                                  |
| ------------- | -------------------------------------------- |
| `/start`      | Welcome + your current plan                  |
| `/model`      | Switch the Claude model (locked on free plan)|
| `/status`     | Your plan and remaining free requests        |
| `/subscribe`  | Buy a subscription (Telegram Stars)          |
| `/reset`      | Clear this chat's conversation               |
| `/help`       | Show help                                    |

Admin-only (set `ADMIN_USER_IDS` in `.env`):

| Command                 | Description                          |
| ----------------------- | ------------------------------------ |
| `/grant <user_id> [days]` | Grant a subscription manually      |
| `/revoke <user_id>`       | Revoke a subscription              |

Any other text message is sent to Claude.

## Subscriptions

- **Free plan:** `claude-haiku-4-5` only, `FREE_REQUEST_LIMIT` (default 10)
  requests. Other models are locked.
- **Subscriber:** all models, no request limit, for `SUBSCRIPTION_DAYS` days.
- Payment uses **Telegram Stars** (`XTR`) — no payment provider token needed.
  Tune `SUBSCRIPTION_PRICE_STARS` and `SUBSCRIPTION_DAYS` in `.env`.
- User state (usage count, subscription expiry) is stored in `bot_state.json`
  (git-ignored).

## Models

Configured in `config.py` (`AVAILABLE_MODELS`):

- `claude-opus-4-8` — most capable
- `claude-sonnet-4-6` — balanced
- `claude-haiku-4-5` — fastest

## Security notes

- **Never commit `.env`** — it's git-ignored. Only `.env.example` (placeholders)
  is tracked.
- If a token or API key is ever exposed, **rotate it immediately**
  (BotFather `/revoke`, Anthropic Console key rotation).
- Use `ALLOWED_USER_IDS` to keep the bot (and your API spend) private.

## Notes

- Replies are sent as plain text and split automatically at Telegram's
  4096-character limit, so code blocks and Markdown from Claude always arrive
  intact without parse errors.
- Conversation history is kept in memory per chat and trimmed to the last
  `MAX_HISTORY_MESSAGES` messages (see `config.py`). It resets if the bot
  restarts.
