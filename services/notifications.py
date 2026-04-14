"""
Admin notification helper.
Sends purchase/renewal alerts to all admin/owner users.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

logger = logging.getLogger(__name__)


async def notify_admins(
    session: AsyncSession,
    bot: Bot,
    text: str,
) -> None:
    """Send a text notification to all admin/owner users."""
    result = await session.execute(
        select(User).where(
            User.role.in_(["admin", "owner"]),
            User.status == "active",
        )
    )
    admins = list(result.scalars().all())

    for admin in admins:
        try:
            await bot.send_message(admin.telegram_id, text)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning(
                "Could not notify admin %s (tg=%s): %s",
                admin.id, admin.telegram_id, exc,
            )
        except Exception as exc:
            logger.error(
                "Unexpected error notifying admin %s: %s",
                admin.id, exc,
            )
