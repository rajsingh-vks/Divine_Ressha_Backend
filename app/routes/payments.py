from datetime import UTC, datetime

import razorpay
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.payments import (
    RazorpayCreateOrderRequest,
    RazorpayOrderOut,
    RazorpayVerifyOut,
    RazorpayVerifyRequest,
)


router = APIRouter(prefix="/payments", tags=["Payments"])
settings = get_settings()


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id format.") from exc


def _razorpay_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Razorpay is not configured on the server.",
        )
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


async def _load_user_order(request: Request, order_id: str, current_user: dict) -> dict:
    db = request.app.state.mongo_db
    order = await db.orders.find_one({"_id": _to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order.get("user_id") != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    return order


@router.post("/razorpay/order", response_model=RazorpayOrderOut)
async def create_razorpay_order(
    payload: RazorpayCreateOrderRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order = await _load_user_order(request, payload.order_id, current_user)

    if order.get("status") == "cancelled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot pay for a cancelled order.")

    subtotal = float(order.get("subtotal") or 0)
    if subtotal <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order amount is invalid.")

    if order.get("payment_status") == "paid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order is already paid.")

    amount_paise = int(round(subtotal * 100))
    currency = settings.razorpay_currency

    client = _razorpay_client()
    razor_order = client.order.create(
        {
            "amount": amount_paise,
            "currency": currency,
            "receipt": order.get("order_number", str(order["_id"])),
            "payment_capture": 1,
            "notes": {"backend_order_id": str(order["_id"])},
        }
    )

    now = datetime.now(UTC)
    await db.orders.update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "payment_provider": "razorpay",
                "payment_status": "created",
                "razorpay_order_id": razor_order["id"],
                "updated_at": now,
            }
        },
    )

    await db.payments.update_one(
        {"backend_order_id": order["_id"]},
        {
            "$set": {
                "backend_order_id": order["_id"],
                "user_id": order["user_id"],
                "provider": "razorpay",
                "provider_order_id": razor_order["id"],
                "amount": amount_paise,
                "currency": currency,
                "status": "created",
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    return RazorpayOrderOut(
        key_id=settings.razorpay_key_id,
        backend_order_id=str(order["_id"]),
        order_number=order.get("order_number", str(order["_id"])),
        razorpay_order_id=razor_order["id"],
        amount=amount_paise,
        currency=currency,
    )


@router.post("/razorpay/verify", response_model=RazorpayVerifyOut)
async def verify_razorpay_payment(
    payload: RazorpayVerifyRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order = await _load_user_order(request, payload.order_id, current_user)

    client = _razorpay_client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Razorpay signature.") from exc

    now = datetime.now(UTC)
    new_order_status = "confirmed" if order.get("status") == "placed" else order.get("status", "placed")

    await db.orders.update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "payment_provider": "razorpay",
                "payment_status": "paid",
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "status": new_order_status,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": new_order_status,
                    "note": "Payment verified via Razorpay.",
                    "changed_at": now,
                    "changed_by": str(current_user["_id"]),
                }
            },
        },
    )

    await db.payments.update_one(
        {"backend_order_id": order["_id"]},
        {
            "$set": {
                "provider": "razorpay",
                "provider_order_id": payload.razorpay_order_id,
                "provider_payment_id": payload.razorpay_payment_id,
                "status": "paid",
                "updated_at": now,
            },
            "$setOnInsert": {
                "backend_order_id": order["_id"],
                "user_id": order["user_id"],
                "created_at": now,
            },
        },
        upsert=True,
    )

    return RazorpayVerifyOut(
        success=True,
        message="Payment verified successfully.",
        backend_order_id=str(order["_id"]),
        payment_status="paid",
        order_status=new_order_status,
    )
