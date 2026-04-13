from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from apps.bot.middlewares.admin import AdminOnlyMiddleware
from core.texts import AdminButtons, AdminMessages
from repositories.admin import AdminStatsRepository


router = Router(name="admin-stats")
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())


@router.callback_query(F.data == "admin:stats")
async def admin_stats_dashboard(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()

    stats_repository = AdminStatsRepository(session)
    total_users = await stats_repository.get_total_users()
    total_active_subscriptions = await stats_repository.get_total_active_subscriptions()
    total_revenue = await stats_repository.get_total_revenue()
    total_active_servers = await stats_repository.get_total_active_servers()

    builder = InlineKeyboardBuilder()
    builder.button(text=AdminButtons.BACK, callback_data="admin:main")
    builder.adjust(1)

    await callback.message.answer(
        AdminMessages.STATS_DASHBOARD.format(
            total_users=total_users,
            total_active_subscriptions=total_active_subscriptions,
            total_revenue=total_revenue,
            total_active_servers=total_active_servers,
        ),
        reply_markup=builder.as_markup(),
    )
