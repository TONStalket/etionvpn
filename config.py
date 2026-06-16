"""Configuration loaded from environment variables (.env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


# Models the user can switch between. Order controls the keyboard layout.
# IDs are the exact Anthropic model strings — do not append date suffixes.
AVAILABLE_MODELS: dict[str, str] = {
    "claude-opus-4-8": "Opus 4.8 · most capable",
    "claude-sonnet-4-6": "Sonnet 4.6 · balanced",
    "claude-haiku-4-5": "Haiku 4.5 · fastest",
}

# Free plan: only this model, limited number of requests.
FREE_MODEL = "claude-haiku-4-5"
FREE_REQUEST_LIMIT = 10

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-opus-4-8")
if DEFAULT_MODEL not in AVAILABLE_MODELS:
    DEFAULT_MODEL = "claude-opus-4-8"

# Subscription (Telegram Stars). provider_token is empty for Stars (XTR).
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "150"))
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))

# Anthropic generation settings.
MAX_TOKENS = 8000
SYSTEM_PROMPT = (
    "You are a helpful assistant running inside a Telegram bot. "
    "Keep replies clear and reasonably concise for a chat interface. "
    "Use Telegram-friendly Markdown when it helps readability."
)

# How many messages to keep in memory per chat.
MAX_HISTORY_MESSAGES = 40

# Commands shown in the Telegram "/" menu and the menu button.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Запустить бота / приветствие"),
    ("model", "Выбрать модель Claude"),
    ("status", "Мой план и остаток запросов"),
    ("subscribe", "Оформить подписку"),
    ("reset", "Очистить историю чата"),
    ("help", "Помощь"),
]


def _parse_user_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return ids


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    anthropic_api_key: str
    allowed_user_ids: set[int] = field(default_factory=set)
    admin_user_ids: set[int] = field(default_factory=set)


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    missing = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not api_key:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        raise SystemExit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ".\nCopy .env.example to .env and fill in your secrets."
        )

    return Settings(
        telegram_token=token,
        anthropic_api_key=api_key,
        allowed_user_ids=_parse_user_ids(os.getenv("ALLOWED_USER_IDS")),
        admin_user_ids=_parse_user_ids(os.getenv("ADMIN_USER_IDS")),
    )
