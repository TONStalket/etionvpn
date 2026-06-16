"""Telegram bot that talks to Claude, with switchable models.

Run with:  python bot.py
Secrets are read from environment variables / .env — see .env.example.
"""
from __future__ import annotations

import logging

import anthropic
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("claude-tg-bot")

SETTINGS = config.load_settings()
client = anthropic.AsyncAnthropic(api_key=SETTINGS.anthropic_api_key)

TELEGRAM_LIMIT = 4096


# --------------------------------------------------------------------------- #
# Per-chat state helpers (stored in context.chat_data)
# --------------------------------------------------------------------------- #
def get_model(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.chat_data.get("model", config.DEFAULT_MODEL)


def get_history(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    return context.chat_data.setdefault("history", [])


def trim_history(history: list[dict]) -> None:
    """Keep memory bounded; drop oldest turns first."""
    excess = len(history) - config.MAX_HISTORY_MESSAGES
    if excess > 0:
        del history[:excess]


def is_authorized(update: Update) -> bool:
    if not SETTINGS.allowed_user_ids:
        return True
    user = update.effective_user
    return user is not None and user.id in SETTINGS.allowed_user_ids


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return
    label = config.AVAILABLE_MODELS[get_model(context)]
    await update.message.reply_text(
        "👋 Hi! I'm a Claude-powered chat bot.\n\n"
        f"Current model: {label}\n\n"
        "Just send me a message. Commands:\n"
        "/model — switch the Claude model\n"
        "/reset — clear this chat's history\n"
        "/help — show help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    context.chat_data["history"] = []
    await update.message.reply_text("🧹 Conversation history cleared.")


def _model_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for model_id, label in config.AVAILABLE_MODELS.items():
        prefix = "✅ " if model_id == current else ""
        buttons.append(
            [InlineKeyboardButton(f"{prefix}{label}", callback_data=f"model:{model_id}")]
        )
    return InlineKeyboardMarkup(buttons)


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "Choose a model:",
        reply_markup=_model_keyboard(get_model(context)),
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_authorized(update):
        return

    chosen = query.data.split(":", 1)[1]
    if chosen not in config.AVAILABLE_MODELS:
        return

    context.chat_data["model"] = chosen
    label = config.AVAILABLE_MODELS[chosen]
    await query.edit_message_text(
        f"Model switched to: {label}",
        reply_markup=_model_keyboard(chosen),
    )


# --------------------------------------------------------------------------- #
# Message handling
# --------------------------------------------------------------------------- #
async def _send_long(update: Update, text: str) -> None:
    """Send a reply, splitting if it exceeds Telegram's per-message limit."""
    if not text:
        text = "(empty response)"
    for i in range(0, len(text), TELEGRAM_LIMIT):
        await update.message.reply_text(text[i : i + TELEGRAM_LIMIT])


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    user_text = update.message.text
    model = get_model(context)
    history = get_history(context)
    history.append({"role": "user", "content": user_text})
    trim_history(history)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        # Stream to avoid HTTP timeouts on longer replies; we only need the
        # final assembled message for Telegram.
        async with client.messages.stream(
            model=model,
            max_tokens=config.MAX_TOKENS,
            system=config.SYSTEM_PROMPT,
            messages=history,
        ) as stream:
            final = await stream.get_final_message()
    except anthropic.APIStatusError as exc:
        logger.exception("Anthropic API error")
        history.pop()  # don't keep an unanswered user turn
        await update.message.reply_text(f"⚠️ API error ({exc.status_code}). Please try again.")
        return
    except Exception:
        logger.exception("Unexpected error")
        history.pop()
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")
        return

    reply = "".join(block.text for block in final.content if block.type == "text")
    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    await _send_long(update, reply)


def main() -> None:
    app = Application.builder().token(SETTINGS.telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^model:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("Bot starting (default model: %s)…", config.DEFAULT_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
