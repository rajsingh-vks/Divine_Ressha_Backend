from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.payments import (
    CheckoutCreateOrderOut,
    CheckoutCreateOrderRequest,
    CheckoutVerifyPaymentOut,
    CheckoutVerifyPaymentRequest,
)


router = APIRouter(prefix="/api", tags=["Payments"])
settings = get_settings()


async def _call_razorpay_create_order(payload: dict, key_id: str, key_secret: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json=payload,
        )

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Razorpay authentication failed.")

    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create Razorpay order.")

    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid Razorpay response.") from exc


@router.post("/create-order", response_model=CheckoutCreateOrderOut)
async def create_order(payload: CheckoutCreateOrderRequest, current_user=Depends(get_current_user)):
    if payload.amount < 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Minimum amount is 100 paise.")

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Razorpay is not configured on the server.",
        )

    receipt = payload.receipt or f"rcpt_{current_user['_id']}_{int(datetime.now(UTC).timestamp())}"
    order_payload = {
        "amount": payload.amount,
        "currency": payload.currency.upper(),
        "receipt": receipt,
    }

    razor_order = await _call_razorpay_create_order(order_payload, settings.razorpay_key_id, settings.razorpay_key_secret)
    return CheckoutCreateOrderOut(
        order_id=razor_order["id"],
        amount=razor_order.get("amount", payload.amount),
        currency=razor_order.get("currency", payload.currency.upper()),
    )


@router.post("/verify-payment", response_model=CheckoutVerifyPaymentOut)
async def verify_payment(payload: CheckoutVerifyPaymentRequest, current_user=Depends(get_current_user)):
    if not payload.razorpay_order_id or not payload.razorpay_payment_id or not payload.razorpay_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required payment fields.")

    if not settings.razorpay_key_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Razorpay is not configured on the server.",
        )

    message = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8")
    generated_signature = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, payload.razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature mismatch.")

    return CheckoutVerifyPaymentOut(success=True, message="Payment verified successfully.")
