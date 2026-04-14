from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from core.config import settings
from core.database import AsyncSessionFactory
from models.payment import Payment
from services.nowpayments.client import NowPaymentsClient, NowPaymentsClientConfig
from services.payment import process_successful_payment


async def sync_pending_payments() -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Payment).where(Payment.payment_status.in_(["waiting", "confirming", "partially_paid"]))
        )
        payments = list(result.scalars().all())

        async with NowPaymentsClient(
            NowPaymentsClientConfig(
                api_key=settings.nowpayments_api_key,
                base_url=settings.nowpayments_base_url,
            )
        ) as client:
            for payment in payments:
                if not payment.provider_payment_id:
                    continue

                status = await client.get_payment_status(payment.provider_payment_id)
                payment.payment_status = status.payment_status
                if isinstance(payment.callback_payload, dict):
                    payment.callback_payload = {**payment.callback_payload, "nowpayments_status": status.model_dump(mode="json")}
                else:
                    payment.callback_payload = {"nowpayments_status": status.model_dump(mode="json")}

                if status.payment_status in ("finished", "confirmed") and payment.actually_paid is None:
                    paid_amount = status.actually_paid or status.price_amount
                    await process_successful_payment(
                        session=session,
                        payment=payment,
                        amount_to_credit=Decimal(str(paid_amount)),
                    )

        await session.commit()
