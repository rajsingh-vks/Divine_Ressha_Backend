from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path as FilePath
from random import randint

import httpx

import boto3
from bson import ObjectId
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.graphics.shapes import Circle, Drawing, Path, String
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.config import get_settings
from app.dependencies import get_current_user, require_role
from app.schemas.orders import (
    AdminFinancialBreakdownOut,
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
from app.services.notifications import send_order_confirmation_email, send_order_placed_support_email


router = APIRouter(prefix="/orders", tags=["Orders"])

ALLOWED_ORDER_STATUSES = {"placed", "confirmed", "processing", "shipped", "delivered", "cancelled", "returned"}
ALLOWED_REFUND_STATUSES = {"pending", "processed", "rejected"}
settings = get_settings()

_FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"
if _FONT_PATH and FilePath(_FONT_PATH).exists():
    try:
        pdfmetrics.registerFont(TTFont("ArialUnicode", _FONT_PATH))
    except Exception:
        pass


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


def _invoice_path(invoice_number: str) -> FilePath:
    invoice_dir = FilePath(__file__).resolve().parents[2] / "media" / "invoices"
    invoice_dir.mkdir(parents=True, exist_ok=True)
    return invoice_dir / f"{invoice_number}.pdf"


def _build_s3_invoice_url(invoice_number: str) -> str:
    if settings.aws_s3_public_base_url:
        return f"{settings.aws_s3_public_base_url.rstrip('/')}/invoices/{invoice_number}.pdf"

    bucket = settings.aws_s3_bucket
    if not bucket:
        return f"{settings.media_url_prefix}/invoices/{invoice_number}.pdf"

    key = f"invoices/{invoice_number}.pdf"
    client = boto3.client("s3", region_name=settings.aws_region) if settings.aws_region else boto3.client("s3")
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=900,
        )
    except Exception:
        path = f"{settings.media_url_prefix}/invoices/{invoice_number}.pdf"
        if settings.public_base_url:
            return f"{settings.public_base_url}{path}"
        return path


def _build_invoice_url(invoice_number: str) -> str:
    if settings.media_backend == "s3" and settings.aws_s3_bucket:
        return _build_s3_invoice_url(invoice_number)
    path = f"{settings.media_url_prefix}/invoices/{invoice_number}.pdf"
    if settings.public_base_url:
        return f"{settings.public_base_url}{path}"
    return path


def _build_divine_logo_mark() -> Drawing:
    logo_mark = Drawing(110, 110)
    logo_mark.add(Circle(55, 55, 43, strokeColor=colors.HexColor("#D4AF68"), strokeWidth=3, fillColor=None))
    logo_mark.add(String(55, 54, "✦", fontName="Times-BoldItalic", fontSize=18, textAnchor="middle", fillColor=colors.HexColor("#D4AF68")))
    logo_mark.add(String(87, 83, "✦", fontName="Times-BoldItalic", fontSize=10, textAnchor="middle", fillColor=colors.HexColor("#D4AF68")))
    logo_mark.add(String(22, 82, "✦", fontName="Times-BoldItalic", fontSize=10, textAnchor="middle", fillColor=colors.HexColor("#D4AF68")))
    logo_mark.add(String(55, 20, "✦", fontName="Times-BoldItalic", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#D4AF68")))
    logo_mark.add(String(55, 90, "✦", fontName="Times-BoldItalic", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#D4AF68")))
    return logo_mark


def _brand_logo_image() -> Image:
    branding_dir = FilePath(__file__).resolve().parents[1] / "static" / "branding"
    candidates = [
        branding_dir / "divine-reesha-logo.png",
        branding_dir / "divine-reesha-logo.svg",
        branding_dir / "logo.png",
        branding_dir / "divine-reesha-logo-soft-gold.png",
        branding_dir / "divine-reesha-logo-soft-gold.svg",
    ]

    logo_path = next((path for path in candidates if path.exists()), None)
    if not logo_path:
        return Image(BytesIO(), width=120, height=40)

    if logo_path.suffix.lower() == ".png":
        return Image(str(logo_path), width=120, height=36)

    import cairosvg

    png_bytes = cairosvg.svg2png(url=str(logo_path), output_width=600, output_height=180)
    return Image(BytesIO(png_bytes), width=120, height=36)


def _build_invoice_pdf_bytes(order: dict, user: dict | None = None) -> bytes:
    invoice_number = _build_invoice_number(order)
    user_name = (user or {}).get("full_name") or "Customer"
    shipping = order.get("shipping_address") or {}
    subtotal = float(order.get("subtotal", 0) or 0)
    discount = float(order.get("discount", 0) or 0)
    shipping_amount = float(order.get("shipping_amount") or order.get("shipping", 0) or 0)
    total = float(order.get("total", subtotal - discount + shipping_amount) or (subtotal - discount + shipping_amount))
    items = order.get("items", [])

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Invoice {invoice_number}",
    )

    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        "Brand",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#2C4E4A"),
        alignment=1,
    )

    wordmark_style = ParagraphStyle(
        "Wordmark",
        parent=styles["Heading1"],
        fontName="Times-Bold",
        fontSize=30,
        leading=32,
        textColor=colors.HexColor("#0F6E6B"),
        alignment=1,
        spaceAfter=8,
    )

    tagline_style = ParagraphStyle(
        "Tagline",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0F6E6B"),
        alignment=1,
        letterSpace=1.5,
    )

    invoice_style = ParagraphStyle(
        "Invoice",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#37261E"),
    )

    logo_mark = _build_divine_logo_mark()

    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["Normal"],
        fontName="ArialUnicode" if FilePath(_FONT_PATH).exists() else "Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#333333"),
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName="ArialUnicode" if FilePath(_FONT_PATH).exists() else "Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#777777"),
    )

    money_style = ParagraphStyle(
        "Money",
        parent=normal_style,
        fontName="ArialUnicode" if FilePath(_FONT_PATH).exists() else "Helvetica",
        alignment=TA_RIGHT,
    )

    story = []

    logo_image = _brand_logo_image()
    if hasattr(logo_image, "hAlign"):
        logo_image.hAlign = "CENTER"

    header = Table(
        [[logo_image]],
        colWidths=[140 * mm],
    )
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(header)
    story.append(Paragraph("BEAUTY • HEALING • HARMONY", tagline_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D7B470"), spaceBefore=6, spaceAfter=14))
    story.append(
        Table(
            [[
                Paragraph(
                    f"<b>Order No:</b> {order.get('order_number', 'N/A')}<br/>"
                    f"<b>Date:</b> {datetime.now(UTC).strftime('%d %b %Y')}<br/>"
                    f"<b>Status:</b> {str(order.get('status', 'Placed')).title()}",
                    normal_style,
                ),
                Paragraph(
                    f"<b>Invoice No:</b> {invoice_number}<br/>"
                    f"<b>Payment:</b> {order.get('payment_provider') or 'Cash'}<br/>"
                    f"<b>Payment Status:</b> {str(order.get('payment_status', 'Unpaid')).title()}",
                    normal_style,
                ),
            ]],
            colWidths=[90 * mm, 80 * mm],
        )
    )
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.7,
            color=colors.HexColor("#D8C9BF"),
            spaceBefore=3,
            spaceAfter=15,
        )
    )

    meta = Table(
        [
            [
                Paragraph(
                    f"<b>Order No:</b> {order.get('order_number', 'N/A')}<br/>"
                    f"<b>Date:</b> {datetime.now(UTC).strftime('%d %b %Y')}<br/>"
                    f"<b>Status:</b> {str(order.get('status', 'Placed')).title()}",
                    normal_style,
                ),
                Paragraph(
                    f"<b>Invoice No:</b> {invoice_number}<br/>"
                    f"<b>Payment:</b> {order.get('payment_provider') or 'Cash'}<br/>"
                    f"<b>Payment Status:</b> {str(order.get('payment_status', 'Unpaid')).title()}",
                    normal_style,
                ),
            ]
        ],
        colWidths=[90 * mm, 80 * mm],
    )
    meta.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(meta)

    billing = Table(
        [
            [
                Paragraph(
                    "<b>BILL TO</b><br/><br/>"
                    f"<b>{user_name}</b><br/>"
                    f"{(user or {}).get('email', '')}<br/>"
                    f"{(user or {}).get('phone', '')}",
                    normal_style,
                ),
                Paragraph(
                    "<b>SHIP TO</b><br/><br/>"
                    f"<b>{shipping.get('full_name', '')}</b><br/>"
                    f"{shipping.get('line1', '')}<br/>"
                    f"{shipping.get('city', '')}, {shipping.get('state', '')}<br/>"
                    f"{shipping.get('postal_code', '')}",
                    normal_style,
                ),
            ]
        ],
        colWidths=[90 * mm, 80 * mm],
    )
    billing.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8F4F1")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3D8D0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(billing)
    story.append(Spacer(1, 15))

    product_rows = [[
        Paragraph("<b>ITEM</b>", small_style),
        Paragraph("<b>QTY</b>", small_style),
        Paragraph("<b>UNIT PRICE</b>", small_style),
        Paragraph("<b>TOTAL</b>", small_style),
    ]]

    for item in items:
        product_rows.append([
            Paragraph(str(item.get("name", "Product")), normal_style),
            Paragraph(str(int(item.get("quantity", 1) or 1)), normal_style),
            Paragraph(f"₹{float(item.get('unit_price') or 0):.2f}", money_style),
            Paragraph(f"₹{float(item.get('line_total') or 0):.2f}", money_style),
        ])

    products = Table(product_rows, colWidths=[95 * mm, 18 * mm, 30 * mm, 27 * mm], repeatRows=1)
    products.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37261E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#37261E")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#E5DDD7")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(products)
    story.append(Spacer(1, 15))

    totals = [
        ["Subtotal", f"₹{subtotal:.2f}"],
        ["Discount", f"- ₹{discount:.2f}"],
        ["Shipping", f"₹{shipping_amount:.2f}"],
        ["TOTAL", f"₹{total:.2f}"],
    ]

    totals_table = Table(totals, colWidths=[140 * mm, 30 * mm])
    totals_table.setStyle(
        TableStyle([
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, -1), (-1, -1), 13),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#37261E")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#37261E")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(totals_table)
    story.append(Spacer(1, 25))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D8C9BF")))
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "<b>Thank you for choosing DIVINE RESSHA.</b><br/>"
            "Beauty • Healing • Harmony<br/><br/>"
            "<font size='7'>"
            "This is a computer-generated invoice and does not require a signature."
            "</font>",
            ParagraphStyle(
                "Footer",
                parent=normal_style,
                alignment=TA_LEFT,
                textColor=colors.HexColor("#6F625B"),
            ),
        )
    )

    doc.build(story)
    return buffer.getvalue()


def _ensure_invoice_pdf(order: dict, user: dict | None = None) -> str:
    invoice_number = _build_invoice_number(order)
    local_path = _invoice_path(invoice_number)
    if not local_path.exists():
        local_path.write_bytes(_build_invoice_pdf_bytes(order, user))

    if settings.media_backend == "s3" and settings.aws_s3_bucket:
        key = f"invoices/{invoice_number}.pdf"
        client = boto3.client("s3", region_name=settings.aws_region) if settings.aws_region else boto3.client("s3")
        client.put_object(Bucket=settings.aws_s3_bucket, Key=key, Body=local_path.read_bytes(), ContentType="application/pdf")

    return _build_invoice_url(invoice_number)


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


@router.get("/financial-breakdown", response_model=AdminFinancialBreakdownOut)
@router.get("/admin/financial-breakdown", response_model=AdminFinancialBreakdownOut)
async def admin_financial_breakdown(
    request: Request,
):
    db = request.app.state.mongo_db

    earned_rows = await db.orders.aggregate(
        [
            {"$match": {"payment_status": "paid"}},
            {"$group": {"_id": None, "amount": {"$sum": {"$toDouble": {"$ifNull": ["$subtotal", 0]}}}}},
        ]
    ).to_list(length=1)
    total_earned = float(earned_rows[0]["amount"]) if earned_rows else 0.0

    refunded_rows = await db.orders.aggregate(
        [
            {"$match": {"refund_status": "processed"}},
            {"$group": {"_id": None, "amount": {"$sum": {"$toDouble": {"$ifNull": ["$refund_amount", 0]}}}}},
        ]
    ).to_list(length=1)
    total_refunded = float(refunded_rows[0]["amount"]) if refunded_rows else 0.0

    total_orders = await db.orders.count_documents({})
    total_refund_orders = await db.orders.count_documents({"refund_status": "processed"})
    total_products = await db.products.count_documents({})
    total_customers = await db.users.count_documents(
        {
            "role": "customer",
            "status": {"$ne": "deleted"},
        }
    )

    return AdminFinancialBreakdownOut(
        total_earned=round(total_earned, 2),
        total_refunded=round(total_refunded, 2),
        net_revenue=round(total_earned - total_refunded, 2),
        total_orders=total_orders,
        total_refund_orders=total_refund_orders,
        total_products=total_products,
        total_customers=total_customers,
        currency=settings.razorpay_currency,
    )


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

    user = await db.users.find_one({"_id": user_id})
    customer_email = (user or {}).get("email")
    if customer_email:
        send_order_confirmation_email(settings, customer_email, created)

    support_email = getattr(settings, "support_email", None) or getattr(settings, "ses_from_email", None) or getattr(settings, "smtp_from_email", None)
    if support_email and customer_email:
        send_order_placed_support_email(settings, support_email, created, customer_email)

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
    user = await db.users.find_one({"_id": order["user_id"]})
    invoice_url = _ensure_invoice_pdf(order, user)
    invoice_generated_at = order.get("invoice_generated_at") or now

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
    user = await db.users.find_one({"_id": order["user_id"]})
    invoice_url = _ensure_invoice_pdf(order, user)
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
