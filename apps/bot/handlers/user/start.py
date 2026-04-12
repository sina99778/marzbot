from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from apps.bot.keyboards.user import get_main_menu_keyboard
from core.texts import Messages
from repositories.user import UserRepository


router = Router(name="user-start")


@router.message(CommandStart())
async def start_command_handler(message: Message, session: AsyncSession) -> None:
    """
    Onboard the Telegram user into the local database and ensure a wallet exists.
    """
    if message.from_user is None:
        return

    telegram_user = message.from_user

    user_repository = UserRepository(session)

    user, is_created = await user_repository.get_or_create_user(
        telegram_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        last_name=telegram_user.last_name,
        language_code=telegram_user.language_code,
    )

    welcome_name = user.first_name or telegram_user.first_name or "دوست عزیز"

    if is_created:
        welcome_text = Messages.WELCOME_NEW.format(name=welcome_name)
    else:
        welcome_text = Messages.WELCOME_BACK.format(name=welcome_name)

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
    )
