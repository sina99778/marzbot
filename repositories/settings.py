from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.texts import MarketingTexts
from models.app_setting import AppSetting


RETARGETING_SETTINGS_KEY = "marketing.retargeting"


@dataclass(slots=True)
class RetargetingSettings:
    enabled: bool
    days: int
    message: str


class AppSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_retargeting_settings(self) -> RetargetingSettings:
        record = await self._get_or_create_retargeting_record()
        payload = dict(record.value_json or {})
        message = str(payload.get("message") or MarketingTexts.RETARGETING_REMINDER)

        return RetargetingSettings(
            enabled=bool(payload.get("enabled", True)),
            days=max(int(payload.get("days", 30)), 1),
            message=message,
        )

    async def update_retargeting_settings(
        self,
        *,
        enabled: bool | None = None,
        days: int | None = None,
        message: str | None = None,
    ) -> RetargetingSettings:
        record = await self._get_or_create_retargeting_record()
        payload = dict(record.value_json or {})

        if enabled is not None:
            payload["enabled"] = enabled
        if days is not None:
            payload["days"] = max(days, 1)
        if message is not None:
            payload["message"] = message.strip()

        record.value_json = payload
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return await self.get_retargeting_settings()

    async def _get_or_create_retargeting_record(self) -> AppSetting:
        record = await self.session.get(AppSetting, RETARGETING_SETTINGS_KEY)
        if record is not None:
            return record

        record = AppSetting(
            key=RETARGETING_SETTINGS_KEY,
            value_json={
                "enabled": True,
                "days": 30,
                "message": MarketingTexts.RETARGETING_REMINDER,
            },
        )
        self.session.add(record)
        await self.session.flush()
        return record
