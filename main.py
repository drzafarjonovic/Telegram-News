"""
Telegram-News — asosiy ishga tushirish nuqtasi.

Bitta asyncio event loopda quyidagilarni birga ishlatadi:
  • aiogram bot (foydalanuvchi va admin interfeysi)
  • Telethon userbot (kanallarni realtime kuzatish)
  • APScheduler (digestlarni belgilangan vaqtda yuborish)
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import config
from app import ai_analyzer, runtime
from app import userbot as userbot_mod
from app.db.pool import db, init_db
from app.scheduler import DigestScheduler
from app.bot.handlers import UserMiddleware, user_router
from app.bot.admin_handlers import admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram-news")


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ishga tushirish"),
            BotCommand(command="add", description="Kanal qo'shish"),
            BotCommand(command="list", description="Kanallarim ro'yxati"),
            BotCommand(command="remove", description="Kanalni o'chirish"),
            BotCommand(command="time", description="Digest vaqtini sozlash"),
            BotCommand(command="help", description="Yordam"),
        ]
    )


async def main() -> None:
    # 1. Sozlamalarni tekshirish
    errors = config.validate()
    if errors:
        logger.error("Sozlamalarda xatolik:\n - %s", "\n - ".join(errors))
        raise SystemExit(1)

    # 2. Ma'lumotlar bazasi
    await init_db(config.database_url)

    # 3. AI
    ai_analyzer.init_analyzer()

    # 4. Bot va Dispatcher
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Routerlar (admin avval — buyruqlar ustunligi uchun)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Middleware (faqat oddiy foydalanuvchi oqimi uchun)
    user_router.message.middleware(UserMiddleware())
    user_router.callback_query.middleware(UserMiddleware())

    # 5. Userbot
    userbot = userbot_mod.init_userbot()
    await userbot.start()

    # 6. Scheduler
    scheduler = DigestScheduler(bot)
    scheduler.start()
    runtime.scheduler_ref = scheduler

    await _set_commands(bot)
    logger.info("Hammasi ishga tushdi. Bot polling boshlanmoqda...")

    # 7. Bot polling va userbot kuzatuvini birga ishlatamiz
    try:
        await asyncio.gather(
            dp.start_polling(bot, handle_signals=False),
            userbot.client.run_until_disconnected(),
        )
    finally:
        logger.info("To'xtatilmoqda...")
        scheduler.shutdown()
        await userbot.stop()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Dastur to'xtatildi.")
