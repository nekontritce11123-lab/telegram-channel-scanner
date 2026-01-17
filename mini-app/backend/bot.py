"""
Reklamshik Bot - Telegram бот для Mini App.
Команды:
  /start - Открыть Mini App
  /check @channel - Быстрая проверка канала
"""

import asyncio
import os
import sys
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from dotenv import load_dotenv

# Добавляем путь к scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан! Добавьте в .env файл")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ads.factchain-traker.online")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Pyrogram клиент для сканирования
pyrogram_client = None


async def get_pyrogram_client():
    """Ленивая инициализация Pyrogram клиента."""
    global pyrogram_client
    if pyrogram_client is None:
        from scanner.client import get_client
        pyrogram_client = get_client()
    if not pyrogram_client.is_connected:
        await pyrogram_client.start()
    return pyrogram_client


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие и кнопка Mini App."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔍 Открыть Рекламщик",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
    ])

    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я анализирую качество Telegram каналов для рекламодателей.\n\n"
        "<b>Что внутри:</b>\n"
        "• 332+ проверенных каналов\n"
        "• Проверка любого канала\n"
        "• Рекомендации по CPM\n\n"
        "Нажми кнопку ниже 👇",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@router.message(Command("check"))
async def cmd_check(message: Message):
    """Быстрая проверка канала без Mini App."""
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "Использование: /check @channel_name\n\n"
            "Пример: /check @durov"
        )
        return

    channel = args[1].strip().lstrip("@")

    # Отправляем статус
    status_msg = await message.answer(f"Сканирую @{channel}...")

    try:
        from scanner.client import smart_scan_safe
        from scanner.scorer import calculate_final_score

        client = await get_pyrogram_client()
        scan_result = await smart_scan_safe(client, channel)

        if scan_result.chat is None:
            error_reason = scan_result.channel_health.get("reason", "Не найден")
            await status_msg.edit_text(f"Ошибка: {error_reason}")
            return

        result = calculate_final_score(
            scan_result.chat,
            scan_result.messages,
            scan_result.comments_data,
            scan_result.users,
            scan_result.channel_health
        )

        # Emoji для вердикта
        verdict_emoji = {
            "EXCELLENT": "🟢",
            "GOOD": "🔵",
            "MEDIUM": "🟡",
            "HIGH_RISK": "🔴",
            "SCAM": "⛔",
        }

        emoji = verdict_emoji.get(result.get("verdict", ""), "⚪")
        categories = result.get("categories", {})

        # Формируем текст
        text = f"""
{emoji} <b>{result.get('verdict', 'N/A')}</b>

<b>Канал:</b> @{channel}
<b>Подписчики:</b> {result.get('members', 0):,}
<b>Score:</b> {result.get('score', 0)}/100
<b>Trust:</b> x{result.get('trust_factor', 1.0):.2f}

<b>Категории:</b>
• Качество: {categories.get('quality', {}).get('score', 0)}/{categories.get('quality', {}).get('max', 40)}
• Engagement: {categories.get('engagement', {}).get('score', 0)}/{categories.get('engagement', {}).get('max', 40)}
• Репутация: {categories.get('reputation', {}).get('score', 0)}/{categories.get('reputation', {}).get('max', 20)}
"""

        # Кнопка для детального анализа
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔍 Открыть в приложении",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )],
            [InlineKeyboardButton(
                text="📢 Перейти в канал",
                url=f"https://t.me/{channel}"
            )],
        ])

        await status_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    except Exception as e:
        await status_msg.edit_text(f"Ошибка сканирования: {str(e)}")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Статистика базы."""
    from scanner.database import CrawlerDB

    db_path = os.getenv("DATABASE_PATH", "crawler.db")
    db = CrawlerDB(db_path)
    stats = db.get_stats()
    cat_stats = db.get_category_stats()
    db.close()

    # Топ категории
    top_cats = sorted(cat_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    cats_text = "\n".join([f"• {cat}: {count}" for cat, count in top_cats])

    text = f"""
<b>База каналов</b>

Всего: {stats.get('total', 0)}
✅ GOOD: {stats.get('good', 0)}
❌ BAD: {stats.get('bad', 0)}
⏳ В очереди: {stats.get('waiting', 0)}

<b>Топ категории:</b>
{cats_text}
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Открыть приложение",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
    ])

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка."""
    text = """
<b>Команды:</b>

/start - Открыть Mini App
/check @channel - Проверить канал
/stats - Статистика базы
/help - Эта справка

<b>Как это работает:</b>
Бот анализирует каналы по 13+ факторам накрутки и выдаёт оценку от 0 до 100.

<b>Вердикты:</b>
🟢 EXCELLENT (75+) - Отличный канал
🔵 GOOD (55-74) - Хороший канал
🟡 MEDIUM (40-54) - Средний
🔴 HIGH_RISK (25-39) - Высокий риск
⛔ SCAM (<25) - Накрутка
"""
    await message.answer(text, parse_mode=ParseMode.HTML)


dp.include_router(router)


async def main():
    """Запуск бота."""
    print(f"Бот запущен: {BOT_TOKEN[:20]}...")
    print(f"Mini App URL: {WEBAPP_URL}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
