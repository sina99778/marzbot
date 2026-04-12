from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from apps.bot.keyboards.inline import (
    build_topup_link_keyboard,
    build_wallet_profile_keyboard,
    build_wallet_topup_keyboard,
)
from apps.bot.states.wallet import TopUpStates
from core.config import settings
from core.texts import Buttons, Messages
from models.payment import Payment
from repositories.user import UserRepository
from schemas.internal.nowpayments import NowPaymentsPaymentCreateRequest
from services.nowpayments.client import NowPaymentsClient, NowPaymentsClientConfig, NowPaymentsRequestError


router = Router(name="user-topup")


@router.message(F.text == Buttons.PROFILE_WALLET)
async def wallet_profile_handler(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await UserRepository(session).get_by_telegram_id(message.from_user.id)
    if user is None or user.wallet is None:
        await message.answer(Messages.WALLET_NOT_FOUND)
        return

    await message.answer(
        Messages.PROFILE_OVERVIEW.format(
            name=user.first_name or "کاربر",
            balance=user.wallet.balance,
            credit_limit=user.wallet.credit_limit,
        ),
        reply_markup=build_wallet_profile_keyboard(),
    )


@router.callback_query(F.data == "wallet:topup")
async def topup_options_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        Messages.TOPUP_CHOOSE_AMOUNT,
        reply_markup=build_wallet_topup_keyboard(),
    )


@router.callback_query(F.data.startswith("wallet:topup:preset:"))
async def topup_preset_handler(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    await callback.answer()
    raw_amount = callback.data.rsplit(":", 1)[-1]
    amount = Decimal(raw_amount)
    await _create_topup_invoice(callback.from_user.id, amount, callback.message, session)


@router.callback_query(F.data == "wallet:topup:custom")
async def topup_custom_amount_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(TopUpStates.waiting_for_custom_amount)
    await callback.message.answer(Messages.TOPUP_ENTER_CUSTOM)


@router.message(TopUpStates.waiting_for_custom_amount)
async def topup_custom_amount_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or message.text is None:
        return

    try:
        amount = Decimal(message.text.strip())
    except InvalidOperation:
        await message.answer(Messages.TOPUP_INVALID_AMOUNT)
        return

    if amount <= Decimal("0"):
        await message.answer(Messages.TOPUP_AMOUNT_GT_ZERO)
        return

    await state.clear()
    await _create_topup_invoice(message.from_user.id, amount, message, session)


async def _create_topup_invoice(
    telegram_id: int,
    amount: Decimal,
    message: Message,
    session: AsyncSession,
) -> None:
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        await message.answer(Messages.ACCOUNT_NOT_FOUND)
        return

    local_order_id = str(uuid4())
    payload = NowPaymentsPaymentCreateRequest(
        price_amount=amount,
        price_currency="usd",
        pay_currency="usdttrc20",
        order_id=local_order_id,
        order_description=f"Wallet top-up for user {user.id}",
        ipn_callback_url=settings.nowpayments_ipn_callback_url,
    )

    try:
        async with NowPaymentsClient(
            NowPaymentsClientConfig(
                api_key=settings.nowpayments_api_key,
                base_url=settings.nowpayments_base_url,
            )
        ) as client:
            invoice = await client.create_payment_invoice(payload)
    except NowPaymentsRequestError:
        await message.answer(Messages.PAYMENT_GATEWAY_UNAVAILABLE)
        return

    payment = Payment(
        user_id=user.id,
        provider="nowpayments",
        kind="wallet_topup",
        provider_payment_id=None,
        provider_invoice_id=str(invoice.id),
        order_id=local_order_id,
        payment_status="waiting",
        pay_currency="usdttrc20",
        price_currency="USD",
        price_amount=amount,
        invoice_url=str(invoice.invoice_url),
        callback_payload={},
    )
    session.add(payment)
    await session.flush()

    await message.answer(
        Messages.TOPUP_INVOICE_CREATED.format(amount=amount),
        reply_markup=build_topup_link_keyboard(str(invoice.invoice_url)),
    )
