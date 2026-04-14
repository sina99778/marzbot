from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from apps.bot.handlers.user.purchase import _finalize_purchase
from core.config import settings
from models.payment import Payment
from models.plan import Plan
from repositories.user import UserRepository
from services.wallet.manager import WalletManager

logger = logging.getLogger(__name__)

async def process_successful_payment(
    session: AsyncSession,
    payment: Payment,
    amount_to_credit: Decimal,
) -> None:
    if payment.actually_paid is not None:
        return

    payment.actually_paid = amount_to_credit

    # 1. Top up wallet
    wallet_manager = WalletManager(session)
    await wallet_manager.process_transaction(
        user_id=payment.user_id,
        amount=amount_to_credit,
        transaction_type="deposit",
        direction="credit",
        currency=payment.price_currency,
        reference_type="payment",
        reference_id=payment.id,
        description="NOWPayments automated wallet credit",
        metadata={
            "provider": payment.provider,
            "provider_payment_id": payment.provider_payment_id,
            "payment_status": payment.payment_status,
        },
    )

    # 2. If it is direct purchase, attempt provisioning
    if payment.kind == "direct_purchase":
        bot = Bot(token=settings.bot_token.get_secret_value())
        try:
            purchase_meta = payment.callback_payload
            plan_id_str = purchase_meta.get("plan_id")
            if not plan_id_str:
                logger.error("Missing plan_id in purchase metadata for payment %s", payment.id)
                return

            plan_id = UUID(plan_id_str)
            config_name = purchase_meta.get("config_name", "VPN")
            discount_percent = purchase_meta.get("discount_percent", 0)

            user = await UserRepository(session).get_by_id(payment.user_id)
            plan = await session.get(Plan, plan_id)
            if not user or not plan:
                return

            original_price = plan.price
            if discount_percent > 0:
                final_price = (original_price * (Decimal(100 - discount_percent) / Decimal(100))).quantize(Decimal("0.01"))
            else:
                final_price = original_price

            await _finalize_purchase(
                chat_id=user.telegram_id,
                bot=bot,
                session=session,
                user=user,
                plan=plan,
                final_price=final_price,
                original_price=original_price,
                discount_percent=discount_percent,
                config_name=config_name,
                payment_method="nowpayments_gateway",
            )
        finally:
            await bot.session.close()
