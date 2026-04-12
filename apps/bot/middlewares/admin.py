from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.texts import AdminMessages
from repositories.user import UserRepository


class AdminOnlyMiddleware(BaseMiddleware):
    """
    Allow access only to `admin` and `owner` users for protected routers.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data.get("session")
        if not isinstance(session, AsyncSession):
            return await handler(event, data)

        telegram_id = _extract_telegram_id(event)
        if telegram_id is None:
            return None

        user_repository = UserRepository(session)
        user = await user_repository.ensure_admin_access(telegram_id)
        if user is None and telegram_id == settings.owner_telegram_id:
            await _deny_access(event, missing_start=True)
            return None

        if user is None or user.role not in {"admin", "owner"}:
            await _deny_access(event)
            return None

        data["admin_user"] = user
        return await handler(event, data)


def _extract_telegram_id(event: TelegramObject) -> int | None:
    if isinstance(event, Message) and event.from_user is not None:
        return event.from_user.id
    if isinstance(event, CallbackQuery) and event.from_user is not None:
        return event.from_user.id
    return None


async def _deny_access(event: TelegramObject, *, missing_start: bool = False) -> None:
    message_text = (
        "برای فعال شدن دسترسی مدیریت، یک‌بار /start را بزنید و دوباره /admin را امتحان کنید."
        if missing_start
        else AdminMessages.PERMISSION_DENIED
    )
    if isinstance(event, Message):
        await event.answer(message_text)
    elif isinstance(event, CallbackQuery):
        await event.answer(message_text, show_alert=True)
