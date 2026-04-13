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


from repositories.settings import AppSettingsRepository

@router.callback_query(F.data == "admin:stats")
async def admin_stats_dashboard(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()

    stats_repository = AdminStatsRepository(session)
    settings_repository = AppSettingsRepository(session)
    
    reset_at = await settings_repository.get_revenue_reset_at()
    
    total_users = await stats_repository.get_total_users()
    total_active_subscriptions = await stats_repository.get_total_active_subscriptions()
    total_revenue = await stats_repository.get_total_revenue(reset_at=reset_at)
    total_active_servers = await stats_repository.get_total_active_servers()

    builder = InlineKeyboardBuilder()
    builder.button(text=AdminButtons.RESET_REVENUE, callback_data="admin:stats:reset_confirm")
    builder.button(text=AdminButtons.BACK, callback_data="admin:main")
    builder.adjust(1)

    await callback.message.edit_text(
        AdminMessages.STATS_DASHBOARD.format(
            total_users=total_users,
            total_active_subscriptions=total_active_subscriptions,
            total_revenue=total_revenue,
            total_active_servers=total_active_servers,
        ),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:stats:reset_confirm")
async def admin_stats_reset_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، صفر کن", callback_data="admin:stats:reset_now")
    builder.button(text=AdminButtons.BACK, callback_data="admin:stats")
    builder.adjust(1)
    
    await callback.message.edit_text(
        AdminMessages.CONFIRM_RESET_REVENUE,
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:stats:reset_now")
async def admin_stats_reset_now(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    
    settings_repository = AppSettingsRepository(session)
    await settings_repository.reset_revenue()
    
    await callback.message.answer(AdminMessages.REVENUE_RESET_SUCCESS)
    await admin_stats_dashboard(callback, session)
