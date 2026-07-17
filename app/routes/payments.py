from datetime import UTC, datetime

import razorpay
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user, require_role
from app.schemas.payments import (
    RazorpayCreateOrderRequest,
    RazorpayOrderOut,
    RazorpayRefundCreateRequest,
    RazorpayRefundOut,
    RazorpayRefundStatusOut,
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


def _map_razorpay_refund_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"processed", "created"}:
        return "processed"
    if normalized in {"pending"}:
        return "pending"
    if normalized in {"failed", "cancelled"}:
        return "rejected"
    return "pending"


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


@router.post("/razorpay/refund", response_model=RazorpayRefundOut)
async def create_razorpay_refund(
    payload: RazorpayRefundCreateRequest,
    request: Request,
    current_admin=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    order = await _load_user_order(request, payload.order_id, current_admin)

    if (order.get("payment_status") or "").lower() != "paid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Refund is allowed only for paid orders.")

    payment_id = order.get("razorpay_payment_id")
    if not payment_id:
        payment_doc = await db.payments.find_one({"backend_order_id": order["_id"]})
        payment_id = payment_doc.get("provider_payment_id") if payment_doc else None

    if not payment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No Razorpay payment found for this order.")

    full_amount_paise = int(round(float(order.get("subtotal") or 0) * 100))
    refund_amount_paise = payload.amount or int(round(float(order.get("refund_amount") or 0) * 100)) or full_amount_paise
    if refund_amount_paise <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Refund amount is invalid.")
    if full_amount_paise > 0 and refund_amount_paise > full_amount_paise:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Refund amount cannot exceed paid amount.")

    client = _razorpay_client()
    try:
        razor_refund = client.payment.refund(
            payment_id,
            {
                "amount": refund_amount_paise,
                "notes": {
                    "backend_order_id": str(order["_id"]),
                    "reason": (payload.reason or "").strip() or "Refund requested",
                },
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to create refund with Razorpay.") from exc

    now = datetime.now(UTC)
    normalized_refund_status = _map_razorpay_refund_status(razor_refund.get("status"))
    await db.orders.update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "refund_status": normalized_refund_status,
                "refund_amount": round(refund_amount_paise / 100, 2),
                "refund_reason": (payload.reason or "").strip() or order.get("refund_reason"),
                "refund_reference": razor_refund.get("id"),
                "refund_requested_at": now,
                "refunded_at": now if normalized_refund_status == "processed" else None,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": order.get("status", "placed"),
                    "note": f"Refund initiated via Razorpay ({normalized_refund_status}).",
                    "changed_at": now,
                    "changed_by": str(current_admin["_id"]),
                }
            },
        },
    )

    await db.payments.update_one(
        {"backend_order_id": order["_id"]},
        {
            "$set": {
                "provider": "razorpay",
                "provider_payment_id": payment_id,
                "last_refund_id": razor_refund.get("id"),
                "last_refund_status": razor_refund.get("status"),
                "last_refund_amount": refund_amount_paise,
                "updated_at": now,
            },
            "$setOnInsert": {
                "backend_order_id": order["_id"],
                "user_id": order["user_id"],
                "created_at": now,
            },
            "$push": {
                "refunds": {
                    "refund_id": razor_refund.get("id"),
                    "payment_id": payment_id,
                    "amount": refund_amount_paise,
                    "currency": razor_refund.get("currency") or settings.razorpay_currency,
                    "status": razor_refund.get("status"),
                    "created_at": now,
                }
            },
        },
        upsert=True,
    )

    return RazorpayRefundOut(
        success=True,
        message="Refund initiated successfully.",
        backend_order_id=str(order["_id"]),
        refund_id=razor_refund["id"],
        payment_id=payment_id,
        amount=int(razor_refund.get("amount") or refund_amount_paise),
        currency=razor_refund.get("currency") or settings.razorpay_currency,
        status=razor_refund.get("status") or "pending",
    )


@router.get("/razorpay/refund/{refund_id}", response_model=RazorpayRefundStatusOut)
async def get_razorpay_refund_status(
    refund_id: str,
    request: Request,
    current_admin=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    client = _razorpay_client()
    try:
        refund = client.refund.fetch(refund_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch refund status from Razorpay.") from exc

    payment_id = refund.get("payment_id")
    now = datetime.now(UTC)
    normalized_refund_status = _map_razorpay_refund_status(refund.get("status"))

    order = await db.orders.find_one({"refund_reference": refund_id})
    if order:
        await db.orders.update_one(
            {"_id": order["_id"]},
            {
                "$set": {
                    "refund_status": normalized_refund_status,
                    "refunded_at": now if normalized_refund_status == "processed" else order.get("refunded_at"),
                    "updated_at": now,
                }
            },
        )

    await db.payments.update_one(
        {"last_refund_id": refund_id},
        {
            "$set": {
                "last_refund_status": refund.get("status"),
                "updated_at": now,
            }
        },
    )

    return RazorpayRefundStatusOut(
        refund_id=refund.get("id", refund_id),
        payment_id=payment_id or "",
        amount=int(refund.get("amount") or 0),
        currency=refund.get("currency") or settings.razorpay_currency,
        status=refund.get("status") or "pending",
        speed_processed=refund.get("speed_processed"),
        created_at=refund.get("created_at"),
    )
