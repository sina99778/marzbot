from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.formatting import format_volume_bytes
from core.texts import Buttons, Messages
from models.order import Order
from models.plan import Plan
from models.xui import XUIInboundRecord
from repositories.user import UserRepository
from services.provisioning.manager import ProvisioningError, ProvisioningManager
from core.qr import make_qr_bytes
from core.formatting import format_volume_bytes

logger = logging.getLogger(__name__)


router = Router(name="user-free-trial")


def _escape(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


@router.message(F.text == Buttons.FREE_TRIAL)
async def free_trial_handler(message: Message, session: AsyncSession, bot: Bot) -> None:
    if message.from_user is None:
        return

    user_repository = UserRepository(session)
    user = await user_repository.get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(Messages.ACCOUNT_NOT_FOUND)
        return

    if user.has_received_free_trial:
        await message.answer(Messages.TRIAL_ALREADY_RECEIVED)
        return

    trial_plan = await session.scalar(
        select(Plan)
        .options(selectinload(Plan.inbound).selectinload(XUIInboundRecord.server))
        .where(
            Plan.is_active.is_(True),
            or_(Plan.code == "TRIAL_PLAN", Plan.price == Decimal("0")),
        )
    )
    if trial_plan is None:
        await message.answer(Messages.TRIAL_PLAN_NOT_FOUND)
        return
    if trial_plan.inbound is None or not trial_plan.inbound.is_active:
        await message.answer(Messages.TRIAL_PLAN_NOT_FOUND)
        return
    if trial_plan.inbound.server is None or not trial_plan.inbound.server.is_active:
        await message.answer(Messages.TRIAL_PLAN_NOT_FOUND)
        return

    order = Order(
        user_id=user.id,
        plan_id=trial_plan.id,
        status="processing",
        source="bot",
        amount=Decimal("0"),
        currency=trial_plan.currency,
    )
    session.add(order)
    await session.flush()

    try:
        provisioning_manager = ProvisioningManager(session)
        provisioned = await provisioning_manager.provision_subscription(
            user_id=user.id,
            plan_id=trial_plan.id,
            order_id=order.id,
        )
    except ProvisioningError as exc:
        logger.error("Free trial provisioning failed for user %s: %s", user.id, exc)
        order.status = "failed"
        await message.answer(Messages.PROVISIONING_FAILED_REFUNDED)
        return

    await user_repository.mark_free_trial_received(user.id)
    order.status = "provisioned"

    sub_link = provisioned.sub_link
    vless_uri = provisioned.vless_uri
    volume_label = format_volume_bytes(trial_plan.volume_bytes)

    text = (
        "🎁 *اکانت تست رایگان آماده است\!*\n\n"
        f"📦 پلن: *{_escape(trial_plan.name)}*\n"
        f"💾 حجم: *{_escape(volume_label)}*\n"
        f"📅 مدت: *{trial_plan.duration_days} روز*\n"
        "🕐 فعال‌سازی: *از اولین اتصال*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔗 *ساب لینک:*\n"
        f"`{_escape(sub_link)}`\n\n"
        "📋 *کانفیگ مستقیم:*\n"
        f"`{_escape(vless_uri)}`\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📱 QR Code رو اسکن کن یا کانفیگ رو کپی کن"
    )
    await message.answer(text, parse_mode="MarkdownV2")

    qr_bytes = make_qr_bytes(vless_uri)
    if qr_bytes:
        await bot.send_photo(
            chat_id=message.from_user.id,
            photo=BufferedInputFile(qr_bytes, filename="trial_qr.png"),
            caption=f"📷 QR کد تست رایگان *{_escape(trial_plan.name)}*",
            parse_mode="MarkdownV2",
        )
