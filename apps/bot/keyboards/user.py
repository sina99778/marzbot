from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from core.texts import Buttons, Messages


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=Buttons.BUY_CONFIG),
                KeyboardButton(text=Buttons.PROFILE_WALLET),
            ],
            [
                KeyboardButton(text=Buttons.SUPPORT),
                KeyboardButton(text=Buttons.FREE_TRIAL),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder=Messages.MENU_PLACEHOLDER,
    )
