from datetime import UTC, datetime, timedelta
from random import randint

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.config import get_settings
from app.dependencies import get_current_user, require_role
from app.schemas.orders import (
    AddressSnapshot,
    OrderConfirmRequest,
    OrderConfirmationOut,
    OrderCancelRequest,
    OrderCreate,
    OrderInvoiceOut,
    OrderRefundSummaryOut,
    OrderItemOut,
    OrderRefundUpdateRequest,
    OrderReturnRequest,
    OrderTrackingEventOut,
    OrderTrackingOut,
    OrderOut,
    OrderStatusHistory,
    OrderStatusUpdate,
)


router = APIRouter(prefix="/orders", tags=["Orders"])

ALLOWED_ORDER_STATUSES = {"placed", "confirmed", "processing", "shipped", "delivered", "cancelled", "returned"}
ALLOWED_REFUND_STATUSES = {"pending", "processed", "rejected"}
settings = get_settings()


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id format.") from exc


def _new_order_number() -> str:
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    return f"DR-{date_part}-{randint(100000, 999999)}"


def _serialize_order(document: dict) -> OrderOut:
    items = [OrderItemOut(**item) for item in document.get("items", [])]
    history = [OrderStatusHistory(**item) for item in document.get("status_history", [])]
    return OrderOut(
        id=str(document["_id"]),
        order_number=document["order_number"],
        user_id=str(document["user_id"]),
        status=document["status"],
        items=items,
        shipping_address=AddressSnapshot(**document["shipping_address"]),
        total_items=document.get("total_items", 0),
        subtotal=float(document.get("subtotal", 0)),
        notes=document.get("notes"),
        cancel_reason=document.get("cancel_reason"),
        cancelled_at=document.get("cancelled_at"),
        payment_status=document.get("payment_status"),
        return_status=document.get("return_status"),
        return_reason=document.get("return_reason"),
        return_requested_at=document.get("return_requested_at"),
        refund_status=document.get("refund_status"),
        refund_amount=document.get("refund_amount"),
        refund_reason=document.get("refund_reason"),
        refund_reference=document.get("refund_reference"),
        refund_requested_at=document.get("refund_requested_at"),
        refunded_at=document.get("refunded_at"),
        status_history=history,
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _build_invoice_number(order: dict) -> str:
    existing = order.get("invoice_number")
    if existing:
        return str(existing)
    return f"INV-{order.get('order_number', str(order['_id']))}"


def _build_invoice_url(invoice_number: str) -> str:
    path = f"{settings.media_url_prefix}/invoices/{invoice_number}.pdf"
    if settings.public_base_url:
        return f"{settings.public_base_url}{path}"
    return path


def _serialize_tracking(order: dict) -> OrderTrackingOut:
    history = [
        OrderTrackingEventOut(
            status=str(item.get("status", "")),
            note=item.get("note"),
            time=item.get("changed_at") or order.get("updated_at") or order["created_at"],
        )
        for item in order.get("status_history", [])
    ]

    expected_delivery = order.get("expected_delivery")
    if expected_delivery is None and order.get("status") != "delivered":
        expected_delivery = order["created_at"] + timedelta(days=5)

    return OrderTrackingOut(
        order_id=str(order["_id"]),
        order_number=order["order_number"],
        status=order.get("status", "placed"),
        payment_status=order.get("payment_status"),
        courier=order.get("courier"),
        awb=order.get("awb"),
        expected_delivery=expected_delivery,
        timeline=history,
    )


@router.get("", response_model=list[OrderOut])
async def list_orders(
    request: Request,
    current_user=Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
):
    query: dict = {}
    if current_user.get("role") != "admin":
        query["user_id"] = current_user["_id"]

    cursor = request.app.state.mongo_db.orders.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = await cursor.to_list(length=limit)
    return [_serialize_order(item) for item in items]


@router.get("/user/history", response_model=list[OrderOut])
async def my_order_history(
    request: Request,
    current_user=Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
):
    cursor = (
        request.app.state.mongo_db.orders.find({"user_id": current_user["_id"]})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)
    return [_serialize_order(item) for item in items]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(request: Request, order_id: str = Path(...), current_user=Depends(get_current_user)):
    order = await request.app.state.mongo_db.orders.find_one({"_id": _to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    return _serialize_order(order)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def place_order(payload: OrderCreate, request: Request, current_user=Depends(get_current_user)):
    db = request.app.state.mongo_db
    user_id = current_user["_id"]

    address = await db.addresses.find_one({"_id": _to_object_id(payload.address_id), "user_id": user_id})
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery address not found.")

    cart_items = await db.cart.find({"user_id": user_id}).to_list(length=500)
    if not cart_items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty.")

    order_items: list[dict] = []
    subtotal = 0.0
    total_items = 0

    for item in cart_items:
        product = await db.products.find_one({"_id": item["product_id"]})
        if not product:
            continue

        unit_price = product.get("price")
        quantity = int(item.get("quantity", 1))
        line_total = float(unit_price) * quantity if isinstance(unit_price, (int, float)) else None

        order_items.append(
            {
                "product_id": str(product["_id"]),
                "name": product.get("name", "Unknown Product"),
                "image_url": product.get("image_url"),
                "unit_price": float(unit_price) if isinstance(unit_price, (int, float)) else None,
                "quantity": quantity,
                "line_total": round(line_total, 2) if line_total is not None else None,
            }
        )
        total_items += quantity
        if line_total is not None:
            subtotal += line_total

    if not order_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid products found in cart.",
        )

    now = datetime.now(UTC)
    shipping_snapshot = {
        "full_name": address["full_name"],
        "phone": address["phone"],
        "line1": address["line1"],
        "line2": address.get("line2"),
        "city": address["city"],
        "state": address["state"],
        "postal_code": address["postal_code"],
        "country": address["country"],
        "address_type": address.get("address_type", "home"),
    }

    order_doc = {
        "user_id": user_id,
        "order_number": _new_order_number(),
        "status": "placed",
        "items": order_items,
        "shipping_address": shipping_snapshot,
        "address_id": address["_id"],
        "total_items": total_items,
        "subtotal": round(subtotal, 2),
        "notes": payload.notes.strip() if payload.notes else None,
        "payment_status": "unpaid",
        "payment_provider": None,
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "razorpay_signature": None,
        "paid_at": None,
        "cancel_reason": None,
        "cancelled_at": None,
        "return_status": None,
        "return_reason": None,
        "return_requested_at": None,
        "refund_status": None,
        "refund_amount": None,
        "refund_reason": None,
        "refund_reference": None,
        "refund_requested_at": None,
        "refunded_at": None,
        "status_history": [
            {
                "status": "placed",
                "note": "Order placed successfully.",
                "changed_at": now,
                "changed_by": str(user_id),
            }
        ],
        "created_at": now,
        "updated_at": now,
    }
    result = await db.orders.insert_one(order_doc)

    await db.cart.delete_many({"user_id": user_id})
    created = await db.orders.find_one({"_id": result.inserted_id})
    return _serialize_order(created)


@router.patch("/{order_id}/status", response_model=OrderOut)
async def update_order_status(
    payload: OrderStatusUpdate,
    request: Request,
    order_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    normalized = payload.status.strip().lower()
    if normalized not in ALLOWED_ORDER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Allowed: {sorted(ALLOWED_ORDER_STATUSES)}",
        )

    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    now = datetime.now(UTC)
    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "status": normalized,
                "updated_at": now,
                "cancelled_at": now if normalized == "cancelled" else order.get("cancelled_at"),
            },
            "$push": {
                "status_history": {
                    "status": normalized,
                    "note": "Status updated by admin.",
                    "changed_at": now,
                    "changed_by": str(current_admin["_id"]),
                }
            },
        },
    )

    updated = await db.orders.find_one({"_id": order_obj_id})
    return _serialize_order(updated)


@router.patch("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    request: Request,
    payload: OrderCancelRequest,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if order.get("status") in {"delivered", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order cannot be cancelled.")

    now = datetime.now(UTC)
    payment_status = (order.get("payment_status") or "").lower()
    refund_updates = {
        "refund_status": "pending" if payment_status == "paid" else "not_required",
        "refund_amount": float(order.get("subtotal") or 0) if payment_status == "paid" else None,
        "refund_reason": payload.reason.strip() if payload.reason else "Order cancelled by user.",
        "refund_requested_at": now if payment_status == "paid" else None,
    }
    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "status": "cancelled",
                "cancel_reason": payload.reason.strip() if payload.reason else None,
                "cancelled_at": now,
                "updated_at": now,
                **refund_updates,
            },
            "$push": {
                "status_history": {
                    "status": "cancelled",
                    "note": payload.reason.strip() if payload.reason else "Order cancelled.",
                    "changed_at": now,
                    "changed_by": str(current_user["_id"]),
                }
            },
        },
    )
    updated = await db.orders.find_one({"_id": order_obj_id})
    return _serialize_order(updated)


@router.post("/{order_id}/return", response_model=OrderOut)
async def request_order_return(
    payload: OrderReturnRequest,
    request: Request,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if order.get("status") != "delivered":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Return can be requested only for delivered orders.")

    if order.get("return_status") == "requested":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Return is already requested.")

    now = datetime.now(UTC)
    payment_status = (order.get("payment_status") or "").lower()
    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "return_status": "requested",
                "return_reason": payload.reason.strip(),
                "return_requested_at": now,
                "refund_status": "pending" if payment_status == "paid" else "not_required",
                "refund_amount": float(order.get("subtotal") or 0) if payment_status == "paid" else None,
                "refund_reason": payload.reason.strip(),
                "refund_requested_at": now if payment_status == "paid" else None,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": "delivered",
                    "note": "Return requested by customer.",
                    "changed_at": now,
                    "changed_by": str(current_user["_id"]),
                }
            },
        },
    )
    updated = await db.orders.find_one({"_id": order_obj_id})
    return _serialize_order(updated)


@router.patch("/{order_id}/refund", response_model=OrderOut)
async def update_order_refund(
    payload: OrderRefundUpdateRequest,
    request: Request,
    order_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    normalized_status = payload.status.strip().lower()
    if normalized_status not in ALLOWED_REFUND_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid refund status. Allowed: {sorted(ALLOWED_REFUND_STATUSES)}")

    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    now = datetime.now(UTC)
    next_order_status = order.get("status")
    if normalized_status == "processed" and order.get("status") in {"cancelled", "delivered", "shipped", "processing", "confirmed", "placed"}:
        next_order_status = "returned" if order.get("return_status") == "requested" or order.get("status") == "delivered" else "cancelled"

    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "refund_status": normalized_status,
                "refund_reason": payload.reason.strip() if payload.reason else order.get("refund_reason"),
                "refund_reference": payload.refund_reference.strip() if payload.refund_reference else order.get("refund_reference"),
                "refunded_at": now if normalized_status == "processed" else None,
                "status": next_order_status,
                "updated_at": now,
            },
            "$push": {
                "status_history": {
                    "status": next_order_status,
                    "note": f"Refund status updated to {normalized_status}.",
                    "changed_at": now,
                    "changed_by": str(current_admin["_id"]),
                }
            },
        },
    )
    updated = await db.orders.find_one({"_id": order_obj_id})
    return _serialize_order(updated)


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm_order(
    request: Request,
    payload: OrderConfirmRequest | None = None,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if order.get("status") in {"cancelled", "returned"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order cannot be confirmed.")

    now = datetime.now(UTC)
    note = payload.note.strip() if payload and payload.note else "Order confirmed."
    next_payment_status = payload.payment_status.strip().lower() if payload and payload.payment_status else "paid"
    next_paid_at = payload.paid_at if payload and payload.paid_at else (now if next_payment_status == "paid" else order.get("paid_at"))

    payment_updates = {
        "payment_status": next_payment_status,
        "paid_at": next_paid_at,
    }
    if payload and payload.razorpay_order_id:
        payment_updates["razorpay_order_id"] = payload.razorpay_order_id.strip()
        payment_updates["payment_provider"] = "razorpay"
    if payload and payload.razorpay_payment_id:
        payment_updates["razorpay_payment_id"] = payload.razorpay_payment_id.strip()
        payment_updates["payment_provider"] = "razorpay"
    if payload and payload.razorpay_signature:
        payment_updates["razorpay_signature"] = payload.razorpay_signature.strip()
        payment_updates["payment_signature_source"] = "frontend_verified"

    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "status": "confirmed",
                "confirmed_at": now,
                "updated_at": now,
                **payment_updates,
            },
            "$push": {
                "status_history": {
                    "status": "confirmed",
                    "note": note,
                    "changed_at": now,
                    "changed_by": str(current_user["_id"]),
                }
            },
        },
    )

    updated = await db.orders.find_one({"_id": order_obj_id})
    return _serialize_order(updated)


@router.get("/{order_id}/invoice", response_model=OrderInvoiceOut)
async def get_order_invoice(
    request: Request,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    now = datetime.now(UTC)
    invoice_number = _build_invoice_number(order)
    invoice_generated_at = order.get("invoice_generated_at") or now
    invoice_url = _build_invoice_url(invoice_number)

    if not order.get("invoice_number"):
        await db.orders.update_one(
            {"_id": order_obj_id},
            {
                "$set": {
                    "invoice_number": invoice_number,
                    "invoice_url": invoice_url,
                    "invoice_generated_at": invoice_generated_at,
                    "updated_at": now,
                }
            },
        )

    return OrderInvoiceOut(
        order_id=str(order["_id"]),
        order_number=order["order_number"],
        invoice_number=invoice_number,
        invoice_url=invoice_url,
        generated_at=invoice_generated_at,
    )


@router.get("/{order_id}/tracking", response_model=OrderTrackingOut)
@router.get("/{order_id}/track", response_model=OrderTrackingOut)
async def get_order_tracking(
    request: Request,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order = await db.orders.find_one({"_id": _to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    return _serialize_tracking(order)


@router.post("/{order_id}/send-confirmation", response_model=OrderConfirmationOut)
async def send_order_confirmation(
    request: Request,
    payload: OrderConfirmRequest | None = None,
    order_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    order_obj_id = _to_object_id(order_id)
    order = await db.orders.find_one({"_id": order_obj_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if current_user.get("role") != "admin" and order["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    now = datetime.now(UTC)
    invoice_number = _build_invoice_number(order)
    invoice_url = _build_invoice_url(invoice_number)
    next_payment_status = payload.payment_status.strip().lower() if payload and payload.payment_status else (order.get("payment_status") or "unpaid")
    next_paid_at = payload.paid_at if payload and payload.paid_at else (now if next_payment_status == "paid" else order.get("paid_at"))

    payment_updates = {
        "payment_status": next_payment_status,
        "paid_at": next_paid_at,
    }
    if payload and payload.razorpay_order_id:
        payment_updates["razorpay_order_id"] = payload.razorpay_order_id.strip()
        payment_updates["payment_provider"] = "razorpay"
    if payload and payload.razorpay_payment_id:
        payment_updates["razorpay_payment_id"] = payload.razorpay_payment_id.strip()
        payment_updates["payment_provider"] = "razorpay"
    if payload and payload.razorpay_signature:
        payment_updates["razorpay_signature"] = payload.razorpay_signature.strip()
        payment_updates["payment_signature_source"] = "frontend_verified"

    user = await db.users.find_one({"_id": order["user_id"]})
    recipient = user.get("email") if user else None

    await db.orders.update_one(
        {"_id": order_obj_id},
        {
            "$set": {
                "invoice_number": invoice_number,
                "invoice_url": invoice_url,
                "invoice_generated_at": order.get("invoice_generated_at") or now,
                "confirmation_sent_at": now,
                "updated_at": now,
                **payment_updates,
            },
            "$push": {
                "email_logs": {
                    "type": "order_confirmation",
                    "status": "sent",
                    "recipient": recipient,
                    "invoice_number": invoice_number,
                    "sent_at": now,
                    "sent_by": str(current_user["_id"]),
                }
            },
        },
    )

    return OrderConfirmationOut(
        success=True,
        message="Order confirmation recorded.",
        order_id=str(order["_id"]),
        order_number=order["order_number"],
        invoice_url=invoice_url,
    )


@router.get("/{order_id}/refund", response_model=OrderRefundSummaryOut)
async def get_order_refund_summary(
    request: Request,
    order_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    order = await db.orders.find_one({"_id": _to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    return OrderRefundSummaryOut(
        order_id=str(order["_id"]),
        order_number=order["order_number"],
        user_id=str(order["user_id"]),
        order_status=order["status"],
        payment_status=order.get("payment_status"),
        return_status=order.get("return_status"),
        refund_status=order.get("refund_status"),
        refund_amount=order.get("refund_amount"),
        refund_reason=order.get("refund_reason"),
        refund_reference=order.get("refund_reference"),
        refund_requested_at=order.get("refund_requested_at"),
        refunded_at=order.get("refunded_at"),
        updated_at=order["updated_at"],
    )
