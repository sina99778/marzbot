"""
Expiry notification job.
Sends a notification to users whose subscription is about to expire (within 1 day).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import utcnow
from core.formatting import format_volume_bytes
from models.subscription import Subscription
from models.user import User

logger = logging.getLogger(__name__)


async def send_expiry_notifications(session: AsyncSession, bot: Bot) -> None:
    """Notify users about subscriptions expiring within 24 hours."""
    now = utcnow()
    threshold = now + timedelta(hours=24)

    result = await session.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.user),
            selectinload(Subscription.plan),
        )
        .where(
            Subscription.status == "active",
            Subscription.ends_at.isnot(None),
            Subscription.ends_at <= threshold,
            Subscription.ends_at > now,
        )
    )
    subscriptions = list(result.scalars().all())

    for sub in subscriptions:
        user = sub.user
        if user is None or user.is_bot_blocked:
            continue

        plan_name = sub.plan.name if sub.plan else "نامشخص"
        remaining_hours = max(int((sub.ends_at - now).total_seconds() / 3600), 0)
        volume_remaining = format_volume_bytes(max(sub.volume_bytes - sub.used_bytes, 0))

        text = (
            "⚠️ سرویس شما رو به اتمام است!\n\n"
            f"📦 پلن: {plan_name}\n"
            f"⏰ زمان باقی‌مانده: {remaining_hours} ساعت\n"
            f"💾 حجم باقی‌مانده: {volume_remaining}\n\n"
            "برای تمدید از بخش «کانفیگ‌های من» اقدام کنید."
        )

        try:
            await bot.send_message(user.telegram_id, text)
        except TelegramForbiddenError:
            user.is_bot_blocked = True
        except Exception as exc:
            logger.warning("Failed to send expiry notification to %s: %s", user.telegram_id, exc)

    # Also notify about volume-based expiry (>90% used)
    volume_result = await session.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.user),
            selectinload(Subscription.plan),
        )
        .where(
            Subscription.status == "active",
            Subscription.volume_bytes > 0,
        )
    )
    volume_subs = list(volume_result.scalars().all())

    for sub in volume_subs:
        if sub.volume_bytes <= 0:
            continue
        usage_ratio = sub.used_bytes / sub.volume_bytes
        if usage_ratio < 0.9:
            continue

        user = sub.user
        if user is None or user.is_bot_blocked:
            continue

        plan_name = sub.plan.name if sub.plan else "نامشخص"
        volume_remaining = format_volume_bytes(max(sub.volume_bytes - sub.used_bytes, 0))
        pct = round(usage_ratio * 100)

        text = (
            "⚠️ حجم سرویس شما رو به اتمام است!\n\n"
            f"📦 پلن: {plan_name}\n"
            f"📊 مصرف: {pct}%\n"
            f"💾 باقی‌مانده: {volume_remaining}\n\n"
            "برای افزایش حجم از بخش «کانفیگ‌های من» → تمدید اقدام کنید."
        )

        try:
            await bot.send_message(user.telegram_id, text)
        except TelegramForbiddenError:
            user.is_bot_blocked = True
        except Exception as exc:
            logger.warning("Failed to send volume warning to %s: %s", user.telegram_id, exc)
