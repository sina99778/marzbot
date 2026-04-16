from __future__ import annotations

from fastapi import FastAPI

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
import structlog
from contextlib import asynccontextmanager

from apps.api.routes.admin import router as admin_router
from apps.api.routes.miniapp.users import router as miniapp_users_router
from apps.api.routes.webhooks.nowpayments import router as nowpayments_webhook_router
from core.config import settings


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=settings.bot_parse_mode),
    )
    app.state.bot = bot
    yield
    await bot.session.close()


app = FastAPI(title="marzbot-api", version="0.1.0", lifespan=lifespan)
app.include_router(miniapp_users_router, prefix="/api/miniapp", tags=["miniapp"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(nowpayments_webhook_router, prefix="/api/webhooks", tags=["webhooks"])

