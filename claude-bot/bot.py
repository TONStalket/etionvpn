"""Telegram bot for chatting with Claude, with switchable models."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
anthropic_client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("claude-bot")

# model id -> (button label, supports adaptive thinking)
MODELS = {
    "claude-opus-4-8": ("Opus 4.8 — самый умный", True),
    "claude-sonnet-5": ("Sonnet 5 — баланс цены и качества", True),
    "claude-sonnet-4-6": ("Sonnet 4.6 — предыдущий Sonnet", True),
    "claude-haiku-4-5": ("Haiku 4.5 — самый быстрый", False),
}
DEFAULT_MODEL = "claude-opus-4-8"

MAX_HISTORY_MESSAGES = 30  # обрезаем историю, чтобы не раздувать контекст
MAX_TOKENS = 8192
TG_MESSAGE_LIMIT = 4000  # чуть меньше лимита Telegram в 4096

SYSTEM_PROMPT = (
    "Ты — ассистент в Telegram. Отвечай на языке пользователя. "
    "Пиши обычным текстом без markdown-разметки, потому что сообщения "
    "отправляются в Telegram как plain text. Отвечай по существу и не "
    "слишком длинно, если пользователь не просит подробностей."
)

# chat_id -> {"model": str, "history": list[dict]}
chats: dict[int, dict] = {}


def get_chat(chat_id: int) -> dict:
    if chat_id not in chats:
        chats[chat_id] = {"model": DEFAULT_MODEL, "history": []}
    return chats[chat_id]


def model_keyboard(current: str) -> InlineKeyboardMarkup:
    rows = []
    for model_id, (label, _) in MODELS.items():
        mark = "✅ " if model_id == current else ""
        rows.append(
            [InlineKeyboardButton(text=mark + label, callback_data=f"model:{model_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def split_text(text: str, limit: int = TG_MESSAGE_LIMIT) -> list[str]:
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def ask_claude(chat: dict, user_text: str) -> str:
    chat["history"].append({"role": "user", "content": user_text})
    chat["history"] = chat["history"][-MAX_HISTORY_MESSAGES:]

    model = chat["model"]
    _, adaptive = MODELS[model]
    kwargs = {"thinking": {"type": "adaptive"}} if adaptive else {}

    response = await anthropic_client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=chat["history"],
        **kwargs,
    )

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        chat["history"].pop()  # не сохраняем пустой обмен
        return "Модель не вернула текстовый ответ. Попробуйте переформулировать."

    chat["history"].append({"role": "assistant", "content": text})
    return text


dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    chat = get_chat(message.chat.id)
    label, _ = MODELS[chat["model"]]
    await message.answer(
        "Привет! Я бот с Claude от Anthropic.\n\n"
        f"Текущая модель: {label}\n\n"
        "Команды:\n"
        "/model — выбрать модель\n"
        "/new — начать новый диалог (очистить историю)\n"
        "/help — справка\n\n"
        "Просто напишите сообщение — я отвечу."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    models_list = "\n".join(f"• {label}" for label, _ in MODELS.values())
    await message.answer(
        "Я пересылаю ваши сообщения в Claude и помню историю диалога.\n\n"
        f"Доступные модели:\n{models_list}\n\n"
        "/model — переключить модель\n"
        "/new — очистить историю диалога"
    )


@dp.message(Command("model"))
async def cmd_model(message: Message):
    chat = get_chat(message.chat.id)
    await message.answer("Выберите модель:", reply_markup=model_keyboard(chat["model"]))


@dp.callback_query(F.data.startswith("model:"))
async def on_model_selected(callback: CallbackQuery):
    model_id = callback.data.split(":", 1)[1]
    if model_id not in MODELS:
        await callback.answer("Неизвестная модель")
        return
    chat = get_chat(callback.message.chat.id)
    chat["model"] = model_id
    label, _ = MODELS[model_id]
    await callback.message.edit_text(f"Модель переключена: {label}")
    await callback.answer()


@dp.message(Command("new"))
async def cmd_new(message: Message):
    get_chat(message.chat.id)["history"] = []
    await message.answer("История очищена. Начинаем новый диалог.")


@dp.message(F.text)
async def on_text(message: Message, bot: Bot):
    chat = get_chat(message.chat.id)

    typing = asyncio.create_task(keep_typing(bot, message.chat.id))
    try:
        answer = await ask_claude(chat, message.text)
    except APIStatusError as e:
        if chat["history"] and chat["history"][-1]["role"] == "user":
            chat["history"].pop()
        log.warning("Anthropic API error %s: %s", e.status_code, e.message)
        if e.status_code == 429:
            answer = "Слишком много запросов к API. Подождите немного и попробуйте снова."
        elif e.status_code >= 500:
            answer = "Сервис Anthropic временно недоступен. Попробуйте позже."
        else:
            answer = f"Ошибка API ({e.status_code}). Попробуйте /new или другую модель."
    except APIConnectionError:
        answer = "Не удалось соединиться с API Anthropic. Попробуйте ещё раз."
    finally:
        typing.cancel()

    for chunk in split_text(answer):
        await message.answer(chunk)


async def keep_typing(bot: Bot, chat_id: int):
    """Показывает «печатает…», пока готовится ответ."""
    try:
        while True:
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def main():
    bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=None))
    me = await bot.get_me()
    log.info("Запущен бот @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
