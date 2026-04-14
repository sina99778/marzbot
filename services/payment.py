"""
Payment processing service.
Handles IPN callbacks and direct purchase provisioning.
No circular imports — uses ProvisioningManager directly.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

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
        await _handle_direct_purchase(session, payment)


async def _handle_direct_purchase(
    session: AsyncSession,
    payment: Payment,
) -> None:
    """Provision a subscription after a successful direct purchase payment."""
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
            logger.error("User or plan not found for direct purchase payment %s", payment.id)
            return

        original_price = plan.price
        if discount_percent > 0:
            final_price = (original_price * (Decimal(100 - discount_percent) / Decimal(100))).quantize(Decimal("0.01"))
        else:
            final_price = original_price

        # Use ProvisioningManager directly (no circular import)
        from services.provisioning.manager import ProvisioningManager, ProvisioningError
        from models.order import Order
        from core.formatting import format_volume_bytes

        order = Order(
            user_id=user.id,
            plan_id=plan.id,
            status="processing",
            source="gateway",
            amount=final_price,
            currency=plan.currency,
        )
        session.add(order)
        await session.flush()

        # Debit from wallet (was credited above)
        wallet_manager = WalletManager(session)
        await wallet_manager.process_transaction(
            user_id=user.id,
            amount=Decimal(str(final_price)),
            transaction_type="purchase",
            direction="debit",
            currency=plan.currency,
            reference_type="order",
            reference_id=order.id,
            description=f"Purchase of plan {plan.code}",
            metadata={"plan_id": str(plan.id), "config_name": config_name},
        )

        try:
            provisioning_manager = ProvisioningManager(session)
            provisioned = await provisioning_manager.provision_subscription(
                user_id=user.id,
                plan_id=plan.id,
                order_id=order.id,
                config_name=config_name,
            )
        except ProvisioningError as exc:
            logger.error("Provisioning failed for gateway order %s: %s", order.id, exc)
            # Refund
            await wallet_manager.process_transaction(
                user_id=user.id,
                amount=Decimal(str(final_price)),
                transaction_type="refund",
                direction="credit",
                currency=plan.currency,
                reference_type="order",
                reference_id=order.id,
                description="Automatic refund after provisioning failure",
                metadata={"plan_id": str(plan.id)},
            )
            order.status = "refunded"
            await bot.send_message(
                user.telegram_id,
                "❌ خطا در ساخت کانفیگ. مبلغ به کیف پول شما بازگردانده شد."
            )
            return

        order.status = "provisioned"

        volume_label = format_volume_bytes(plan.volume_bytes)
        sub_link = provisioned.sub_link
        vless_uri = provisioned.vless_uri

        text = (
            "✅ کانفیگ شما آماده است!\n\n"
            f"📛 نام: {config_name}\n"
            f"📦 پلن: {plan.name}\n"
            f"💾 حجم: {volume_label}\n"
            f"📅 مدت: {plan.duration_days} روز\n"
            f"💰 پرداخت شده: {final_price:.2f} {plan.currency}\n"
            f"💳 روش: درگاه پرداخت\n"
            f"🕐 فعال‌سازی: از اولین اتصال\n\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🔗 ساب لینک:\n{sub_link}\n\n"
            f"📋 کانفیگ مستقیم:\n{vless_uri}"
        )
        await bot.send_message(user.telegram_id, text)

        # QR Code
        from core.qr import make_qr_bytes
        from aiogram.types import BufferedInputFile
        qr_bytes = make_qr_bytes(vless_uri)
        if qr_bytes:
            await bot.send_photo(
                chat_id=user.telegram_id,
                photo=BufferedInputFile(qr_bytes, filename="config_qr.png"),
                caption=f"📷 QR کد کانفیگ {config_name}",
            )

        # Notify admins
        from services.notifications import notify_admins
        admin_text = (
            "🛒 خرید جدید (درگاه)!\n\n"
            f"👤 کاربر: {user.first_name or '-'} (ID: {user.telegram_id})\n"
            f"📦 پلن: {plan.name}\n"
            f"💰 مبلغ: {final_price:.2f} {plan.currency}\n"
            f"📛 کانفیگ: {config_name}\n"
            f"💳 روش: درگاه پرداخت"
        )
        try:
            await notify_admins(session, bot, admin_text)
        except Exception as exc:
            logger.warning("Failed to notify admins: %s", exc)

    finally:
        await bot.session.close()
