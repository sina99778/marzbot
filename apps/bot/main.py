from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from apps.bot.handlers.admin import router as admin_router
from apps.bot.handlers.user import router as user_router
from apps.bot.middlewares.database import DatabaseSessionMiddleware
from apps.bot.middlewares.error_handler import GlobalErrorMiddleware
from core.config import settings
from core.database import dispose_database


import structlog

def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
    )


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    structlog.get_logger(__name__).info("Bot started", id=me.id, username=f"@{me.username}")


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await dispose_database()


async def main() -> None:
    configure_logging()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=settings.bot_parse_mode),
    )
    dispatcher = Dispatcher()
    dispatcher.update.middleware(DatabaseSessionMiddleware())
    dispatcher.message.middleware(GlobalErrorMiddleware())
    dispatcher.callback_query.middleware(GlobalErrorMiddleware())
    dispatcher.include_router(admin_router)
    dispatcher.include_router(user_router)
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    await dispatcher.start_polling(
        bot,
        drop_pending_updates=settings.bot_drop_pending_updates,
    )


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
