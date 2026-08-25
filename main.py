import asyncio
import logging
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN
from bot.handlers import start, downloader

# Loggingni sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("main")


async def health_check(request):
    """Bepul serverlar (Render, Koyeb) uchun health-check web javobi."""
    return web.Response(text="Telegram Downloader Bot is running 24/7! 🚀", status=200)


async def start_web_server():
    """Bulutli serverlar uchun kichik HTTP serverni ishga tushirish."""
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Veb-server {port}-portda muvaffaqiyatli ishga tushdi.")
    return runner


async def main():
    if not BOT_TOKEN:
        logger.error(
            "XATOLIK: BOT_TOKEN topilmadi! Iltimos, .env faylini ochib, BotFather bergan tokenni kiriting.\n"
            "Misol uchun: .env faylida BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz ko'rinishida bo'lishi kerak."
        )
        return

    logger.info("Bot ishga tushirilmoqda...")

    # Bepul hostinglar (Render/Koyeb) port kutishi uchun web-serverni ishga tushirish
    web_runner = await start_web_server()

    # Bot va Dispatcher yaratish
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Routerlarni ulash
    dp.include_router(start.router)
    dp.include_router(downloader.router)

    # Eski kutilmagan yangilanishlarni o'tkazib yuborish
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(f"Bot muvaffaqiyatli ishga tushdi: @{bot_info.username} ({bot_info.first_name})")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await web_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
