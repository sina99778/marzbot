from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.db import get_db_session
from core.config import settings
from models.payment import Payment
from services.payment import process_successful_payment


router = APIRouter()


@router.post("/nowpayments")
async def handle_nowpayments_ipn(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    signature = request.headers.get("x-nowpayments-sig")
    raw_body = await request.body()

    if not _is_valid_nowpayments_signature(raw_body=raw_body, signature=signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid NOWPayments signature.",
        )

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        ) from exc

    provider_payment_id = str(payload.get("payment_id", "")).strip()
    payment_status = str(payload.get("payment_status", "")).strip().lower()

    if not provider_payment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing payment_id in NOWPayments callback.",
        )

    # Try by provider_payment_id first, then fallback to order_id
    payment = await session.scalar(
        select(Payment).where(Payment.provider_payment_id == provider_payment_id)
    )
    if payment is None:
        # Fallback: look up by order_id from payload
        order_id_from_payload = str(payload.get("order_id", "")).strip()
        if order_id_from_payload:
            payment = await session.scalar(
                select(Payment).where(Payment.order_id == order_id_from_payload)
            )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found.",
        )
    # Store provider_payment_id for future lookups
    if not payment.provider_payment_id:
        payment.provider_payment_id = provider_payment_id

    payment.payment_status = payment_status
    if isinstance(payment.callback_payload, dict):
        payment.callback_payload = {**payment.callback_payload, "nowpayments_ipn": payload}
    else:
        payment.callback_payload = {"nowpayments_ipn": payload}

    if payment_status not in {"finished", "confirmed"}:
        return {"status": "ignored"}

    # Idempotency guard: if we already credited this payment once, do not repeat it.
    if payment.actually_paid is not None:
        return {"status": "already_processed"}

    amount_to_credit = _extract_credit_amount(payload)
    if amount_to_credit <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment amount in callback payload.",
        )

    await process_successful_payment(
        session=session,
        payment=payment,
        amount_to_credit=amount_to_credit,
    )

    return {"status": "processed"}


def _is_valid_nowpayments_signature(*, raw_body: bytes, signature: str | None) -> bool:
    if settings.nowpayments_ipn_secret is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NOWPayments IPN secret is not configured.",
        )

    if not signature:
        return False

    try:
        canonical_body = json.dumps(
            json.loads(raw_body.decode("utf-8")),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False

    expected_signature = hmac.HMAC(
        key=settings.nowpayments_ipn_secret.get_secret_value().encode("utf-8"),
        msg=canonical_body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def _extract_credit_amount(payload: dict[str, Any]) -> Decimal:
    raw_amount = payload.get("actually_paid") or payload.get("price_amount")
    if raw_amount in {None, ""}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing payment amount in callback payload.",
        )

    try:
        return Decimal(str(raw_amount))
    except (InvalidOperation, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment amount in callback payload.",
        ) from exc
