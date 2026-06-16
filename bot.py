"""Telegram bot that talks to Claude, with model switching + subscriptions.

Free plan : Haiku 4.5 only, limited requests.
Subscriber: all models, unlimited. Paid via Telegram Stars or granted by admin.

Run with:  python bot.py
Secrets are read from environment variables / .env — see .env.example.
"""
from __future__ import annotations

import logging
import time

import anthropic
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MenuButtonCommands,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

import config
import storage

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
# State helpers
# --------------------------------------------------------------------------- #
def get_chosen_model(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.chat_data.get("model", config.DEFAULT_MODEL)


def effective_model(user: dict, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Subscribers use their chosen model; free users are pinned to FREE_MODEL."""
    if storage.is_subscribed(user):
        return get_chosen_model(context)
    return config.FREE_MODEL


def get_history(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    return context.chat_data.setdefault("history", [])


def trim_history(history: list[dict]) -> None:
    excess = len(history) - config.MAX_HISTORY_MESSAGES
    if excess > 0:
        del history[:excess]


def is_authorized(update: Update) -> bool:
    if not SETTINGS.allowed_user_ids:
        return True
    user = update.effective_user
    return user is not None and user.id in SETTINGS.allowed_user_ids


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in SETTINGS.admin_user_ids


def free_requests_left(user: dict) -> int:
    return max(0, config.FREE_REQUEST_LIMIT - int(user.get("requests_used", 0)))


def plan_line(user: dict) -> str:
    if storage.is_subscribed(user):
        until = time.strftime("%d.%m.%Y", time.localtime(user["subscribed_until"]))
        return f"⭐️ Подписка активна до {until} — доступны все модели без лимита."
    left = free_requests_left(user)
    return (
        f"🆓 Бесплатный план: модель Haiku 4.5, осталось запросов: {left} из "
        f"{config.FREE_REQUEST_LIMIT}.\nОформи /subscribe — откроются все модели без лимита."
    )


def _subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"⭐️ Оформить за {config.SUBSCRIPTION_PRICE_STARS} Stars", callback_data="buy")]]
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Извините, у вас нет доступа к этому боту.")
        return
    user = storage.get_user(update.effective_user.id)
    await update.message.reply_text(
        "👋 Привет! Я бот на базе Claude.\n\n"
        "Просто пришли любое сообщение — я отвечу.\n\n"
        f"{plan_line(user)}\n\n"
        "Команды:\n"
        "/model — выбрать модель\n"
        "/status — мой план и остаток запросов\n"
        "/subscribe — оформить подписку\n"
        "/reset — очистить историю\n"
        "/help — помощь"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    context.chat_data["history"] = []
    await update.message.reply_text("🧹 История очищена.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    user = storage.get_user(update.effective_user.id)
    await update.message.reply_text(plan_line(user))


# ---- Model picker ---- #
def _model_keyboard(current: str, subscribed: bool) -> InlineKeyboardMarkup:
    buttons = []
    for model_id, label in config.AVAILABLE_MODELS.items():
        locked = (not subscribed) and (model_id != config.FREE_MODEL)
        mark = "✅ " if model_id == current else ""
        if locked:
            label = f"🔒 {label}"
        buttons.append(
            [InlineKeyboardButton(f"{mark}{label}", callback_data=f"model:{model_id}")]
        )
    return InlineKeyboardMarkup(buttons)


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    user = storage.get_user(update.effective_user.id)
    sub = storage.is_subscribed(user)
    current = get_chosen_model(context) if sub else config.FREE_MODEL
    text = "Выберите модель:" if sub else "На бесплатном плане доступна только Haiku 4.5.\nОстальные модели — по подписке (/subscribe)."
    await update.message.reply_text(text, reply_markup=_model_keyboard(current, sub))


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_authorized(update):
        await query.answer()
        return
    chosen = query.data.split(":", 1)[1]
    if chosen not in config.AVAILABLE_MODELS:
        await query.answer()
        return

    user = storage.get_user(update.effective_user.id)
    sub = storage.is_subscribed(user)
    if not sub and chosen != config.FREE_MODEL:
        await query.answer("Доступно по подписке", show_alert=False)
        await query.message.reply_text(
            "🔒 Эта модель доступна только по подписке.",
            reply_markup=_subscribe_keyboard(),
        )
        return

    await query.answer()
    context.chat_data["model"] = chosen
    label = config.AVAILABLE_MODELS[chosen]
    await query.edit_message_text(
        f"Модель выбрана: {label}",
        reply_markup=_model_keyboard(chosen, sub),
    )


# ---- Subscription ---- #
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    user = storage.get_user(update.effective_user.id)
    if storage.is_subscribed(user):
        await update.message.reply_text(plan_line(user))
        return
    await update.message.reply_text(
        f"⭐️ Подписка на {config.SUBSCRIPTION_DAYS} дней.\n"
        "Откроет все модели (Opus 4.8 / Sonnet 4.6 / Haiku 4.5) без лимита.",
        reply_markup=_subscribe_keyboard(),
    )


async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a Telegram Stars invoice."""
    query = update.callback_query
    await query.answer()
    if not is_authorized(update):
        return
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="Подписка Claude Bot",
        description=f"Доступ ко всем моделям без лимита на {config.SUBSCRIPTION_DAYS} дней.",
        payload="subscription",
        provider_token="",  # empty for Telegram Stars
        currency="XTR",
        prices=[LabeledPrice("Подписка", config.SUBSCRIPTION_PRICE_STARS)],
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    storage.grant_subscription(user_id, config.SUBSCRIPTION_DAYS)
    user = storage.get_user(user_id)
    await update.message.reply_text("✅ Спасибо! Подписка активирована.\n\n" + plan_line(user))


# ---- Admin ---- #
async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    try:
        target = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else config.SUBSCRIPTION_DAYS
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /grant <user_id> [дней]")
        return
    storage.grant_subscription(target, days)
    await update.message.reply_text(f"✅ Выдана подписка пользователю {target} на {days} дн.")


async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    try:
        target = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    storage.revoke_subscription(target)
    await update.message.reply_text(f"🚫 Подписка пользователя {target} отозвана.")


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
async def _send_long(update: Update, text: str) -> None:
    if not text:
        text = "(пустой ответ)"
    for i in range(0, len(text), TELEGRAM_LIMIT):
        await update.message.reply_text(text[i : i + TELEGRAM_LIMIT])


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Извините, у вас нет доступа к этому боту.")
        return

    user = storage.get_user(update.effective_user.id)
    subscribed = storage.is_subscribed(user)

    # Quota gate for free users.
    if not subscribed and free_requests_left(user) <= 0:
        await update.message.reply_text(
            "🚫 Бесплатные запросы закончились.\n"
            "Оформи подписку — откроются все модели без лимита.",
            reply_markup=_subscribe_keyboard(),
        )
        return

    model = effective_model(user, context)
    history = get_history(context)
    history.append({"role": "user", "content": update.message.text})
    trim_history(history)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        async with client.messages.stream(
            model=model,
            max_tokens=config.MAX_TOKENS,
            system=config.SYSTEM_PROMPT,
            messages=history,
        ) as stream:
            final = await stream.get_final_message()
    except anthropic.APIStatusError as exc:
        logger.exception("Anthropic API error")
        history.pop()
        await update.message.reply_text(f"⚠️ Ошибка API ({exc.status_code}). Попробуйте ещё раз.")
        return
    except Exception:
        logger.exception("Unexpected error")
        history.pop()
        await update.message.reply_text("⚠️ Что-то пошло не так. Попробуйте ещё раз.")
        return

    reply = "".join(block.text for block in final.content if block.type == "text")
    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    # Count usage only for free users; warn near the limit.
    note = ""
    if not subscribed:
        user["requests_used"] = int(user.get("requests_used", 0)) + 1
        storage.save()
        left = free_requests_left(user)
        if left <= 3:
            note = f"\n\n🆓 Осталось бесплатных запросов: {left}. /subscribe — без лимита."

    await _send_long(update, reply + note)


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #
async def _post_init(app: Application) -> None:
    """Register the command menu and the menu button."""
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in config.BOT_COMMANDS])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Command menu registered.")


def main() -> None:
    app = Application.builder().token(SETTINGS.telegram_token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("grant", grant))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^model:"))
    app.add_handler(CallbackQueryHandler(send_invoice, pattern=r"^buy$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("Bot starting (default model: %s)…", config.DEFAULT_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
