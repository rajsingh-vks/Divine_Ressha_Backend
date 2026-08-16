from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from html import escape
from pathlib import Path

import boto3
import httpx

from app.config import Settings


logger = logging.getLogger(__name__)


def _brand_svg_url(variant: str = "default", settings: Settings | None = None) -> str:
    branding_dir = Path(__file__).resolve().parents[1] / "static" / "branding"
    candidates = []
    if variant == "soft_gold":
        candidates.extend([
            branding_dir / "divine-reesha-logo-soft-gold.png",
            branding_dir / "divine-reesha-logo-soft-gold.svg",
            branding_dir / "divine-reesha-logo.png",
            branding_dir / "divine-reesha-logo.svg",
            branding_dir / "logo.png",
        ])
    else:
        candidates.extend([
            branding_dir / "divine-reesha-logo.png",
            branding_dir / "divine-reesha-logo.svg",
            branding_dir / "logo.png",
            branding_dir / "divine-reesha-logo-soft-gold.png",
            branding_dir / "divine-reesha-logo-soft-gold.svg",
        ])

    logo_path = next((item for item in candidates if item.exists()), None)
    if not logo_path:
        return ""

    settings = settings or Settings()
    public_base = (settings.public_base_url or "").rstrip("/")
    logo_name = logo_path.name
    if public_base:
        return f"{public_base}/branding/{logo_name}"
    return f"/branding/{logo_name}"


def send_email_verification_code(settings: Settings, recipient: str, code: str) -> bool:
    success, _ = send_email_verification_code_detailed(settings, recipient, code)
    return success


def _build_invoice_details(order: dict, settings: Settings) -> tuple[str, str]:
    invoice_number = order.get("invoice_number") or f"INV-{order.get('order_number', 'N/A')}"
    if settings.media_backend == "s3" and settings.aws_s3_bucket:
        if settings.aws_s3_public_base_url:
            invoice_url = f"{settings.aws_s3_public_base_url.rstrip('/')}/invoices/{invoice_number}.pdf"
            return invoice_number, invoice_url
        bucket = settings.aws_s3_bucket
        region = settings.aws_region
        if region:
            invoice_url = f"https://{bucket}.s3.{region}.amazonaws.com/invoices/{invoice_number}.pdf"
        else:
            invoice_url = f"https://{bucket}.s3.amazonaws.com/invoices/{invoice_number}.pdf"
        return invoice_number, invoice_url
    path = f"{settings.media_url_prefix}/invoices/{invoice_number}.pdf"
    invoice_url = f"{settings.public_base_url}{path}" if settings.public_base_url else path
    return invoice_number, invoice_url


def _render_order_items_table(items: list[dict]) -> str:
    if not items:
        return "<p style=\"margin: 16px 0 0; color: #6b7280; font-size: 14px;\">No item details available.</p>"

    rows = []
    for item in items:
        name = escape(str(item.get("name") or "Product"))
        quantity = int(item.get("quantity") or 1)
        unit_price = float(item.get("unit_price") or 0)
        line_total = float(item.get("line_total") or (unit_price * quantity))
        image_url = item.get("image_url") or item.get("product_image_url")
        image_html = ""
        if image_url:
            image_html = (
                "<img src=\"" + escape(str(image_url), quote=True) + "\" "
                "style=\"width: 42px; height: 42px; object-fit: cover; border-radius: 10px; border: 1px solid #ecdcc7; background: #f8f3ef; display: block;\" alt=\"Product\" />"
            )

        rows.append(
            "<tr>"
            f"<td style=\"padding: 10px 8px 10px 0; border-bottom: 1px solid #f1e7db; color: #1f2937;\">"
            f"<div style=\"display: flex; align-items: center; gap: 10px;\">{image_html}<span>{name}</span></div>"
            "</td>"
            f"<td style=\"padding: 10px 8px; border-bottom: 1px solid #f1e7db; color: #4b5563; text-align: center;\">{quantity}</td>"
            f"<td style=\"padding: 10px 0 10px 8px; border-bottom: 1px solid #f1e7db; color: #111827; font-weight: 600; text-align: right;\">₹{line_total:.2f}</td>"
            "</tr>"
        )

    return (
        "<table cellpadding=\"0\" cellspacing=\"0\" width=\"100%\" style=\"border-collapse: collapse; margin-top: 16px;\">"
        "<thead><tr>"
        "<th style=\"padding: 10px 8px 10px 0; text-align: left; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; color: #7c5b49;\">Product</th>"
        "<th style=\"padding: 10px 8px; text-align: center; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; color: #7c5b49;\">Qty</th>"
        "<th style=\"padding: 10px 0 10px 8px; text-align: right; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; color: #7c5b49;\">Total</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _brand_order_html(
    title: str,
    headline: str,
    content_rows: list[tuple[str, str]],
    footer_note: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    items: list[dict] | None = None,
    settings: Settings | None = None,
) -> str:
    rows_html = "".join(
        f"<tr><td style=\"padding: 10px 0; color: #4b5563; font-size: 14px;\">{escape(str(label))}</td><td style=\"padding: 10px 0; color: #111827; font-weight: 600; text-align: right;\">{value}</td></tr>"
        for label, value in content_rows
    )
    item_table_html = _render_order_items_table(items or [])
    cta_html = ""
    if cta_label and cta_url:
        cta_html = (
            "<div style=\"margin-top: 24px; text-align: center;\">"
            f"<a href=\"{escape(cta_url, quote=True)}\" style=\"display: inline-block; background: linear-gradient(135deg, #caa75d 0%, #f4e5ba 22%, #8d693f 100%); color: #24160f; text-decoration: none; font-weight: 700; font-size: 13px; line-height: 1; padding: 16px 28px; border-radius: 999px; letter-spacing: 0.08em; text-transform: uppercase; box-shadow: 0 8px 18px rgba(153, 119, 73, 0.18);\">{escape(cta_label)}</a>"
            "</div>"
        )

    logo_url = _brand_svg_url("soft_gold", settings)
    header_logo = f"<img src=\"{logo_url}\" alt=\"Divine Reesha\" style=\"display: block; width: 180px; max-width: 100%; height: auto; margin-bottom: 14px;\" />" if logo_url else "<div style=\"font-size: 12px; letter-spacing: 2px; text-transform: uppercase; opacity: 0.9;\">Divine Reesha</div>"

    return f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{title}</title>
  </head>
  <body style=\"margin: 0; padding: 0; background-color: #f8f5f1; font-family: 'Georgia', 'Times New Roman', serif; color: #111827;\">
    <div style=\"max-width: 680px; margin: 32px auto; background: #fffdfb; border-radius: 20px; overflow: hidden; border: 1px solid #eadcc9; box-shadow: 0 10px 30px rgba(33, 23, 18, 0.08);\">
      <div style=\"background: linear-gradient(135deg, #201612 0%, #3f281f 35%, #8a6548 100%); padding: 28px 32px 24px; color: #ffffff;\">
        {header_logo}
        <h1 style=\"margin: 0; font-size: 30px; line-height: 1.2; font-family: 'Georgia', 'Times New Roman', serif; font-weight: 600;\">{headline}</h1>
      </div>
      <div style=\"padding: 28px 32px 18px;\">
        <table cellpadding=\"0\" cellspacing=\"0\" width=\"100%\" style=\"border-collapse: collapse;\">
          {rows_html}
        </table>
        {item_table_html}
        {cta_html}
        <p style=\"margin: 24px 0 0; color: #4b5563; font-size: 15px; line-height: 1.8; font-family: Arial, sans-serif;\">{footer_note}</p>
      </div>
      <div style=\"padding: 0 32px 28px; font-size: 12px; color: #6b7280; font-family: Arial, sans-serif;\">
        Warm regards,<br />
        The Divine Reesha Team
      </div>
    </div>
  </body>
</html>
"""


def send_order_confirmation_email(settings: Settings, recipient: str, order: dict) -> tuple[bool, str | None]:
    order_number = order.get("order_number", "N/A")
    subtotal = float(order.get("subtotal", 0) or 0)
    invoice_number, invoice_url = _build_invoice_details(order, settings)
    subject = f"Your Divine Reesha order {order_number} is confirmed"
    body = (
        "Thank you for shopping with Divine Reesha.\n\n"
        f"Order Number: {order_number}\n"
        f"Order Total: ₹{subtotal:.2f}\n"
        f"Invoice Number: {invoice_number}\n"
        f"Invoice: {invoice_url}\n\n"
        "Your order has been placed successfully and is now being processed.\n\n"
        "We will keep you updated as your order moves through fulfillment."
    )
    html_body = _brand_order_html(
        title=f"Order Confirmed - {order_number}",
        headline="Your order is confirmed",
        content_rows=[
            ("Order Number", order_number),
            ("Order Total", f"₹{subtotal:.2f}"),
            ("Invoice Number", invoice_number),
            ("Status", "Placed & Processing"),
        ],
        footer_note="Thank you for choosing Divine Reesha. We’re preparing your order and will keep you informed as it moves toward delivery.",
        cta_label="View invoice",
        cta_url=invoice_url,
        items=order.get("items", []),
        settings=settings,
    )
    return _send_generic_email(settings, recipient, subject, body, html_body)


def send_order_placed_support_email(settings: Settings, recipient: str, order: dict, customer_email: str) -> tuple[bool, str | None]:
    order_number = order.get("order_number", "N/A")
    subtotal = float(order.get("subtotal", 0) or 0)
    invoice_number, invoice_url = _build_invoice_details(order, settings)
    subject = f"New order placed: {order_number}"
    body = (
        "A new order has been placed on Divine Reesha.\n\n"
        f"Order Number: {order_number}\n"
        f"Customer Email: {customer_email}\n"
        f"Order Total: ₹{subtotal:.2f}\n"
        f"Invoice Number: {invoice_number}\n"
        f"Invoice: {invoice_url}\n"
        f"Items: {order.get('total_items', 0)}\n"
        "Please review and fulfill the order."
    )
    html_body = _brand_order_html(
        title=f"New Order - {order_number}",
        headline="New order received",
        content_rows=[
            ("Order Number", order_number),
            ("Customer Email", customer_email),
            ("Order Total", f"₹{subtotal:.2f}"),
            ("Invoice Number", invoice_number),
            ("Items", str(order.get("total_items", 0))),
        ],
        footer_note="A new order has been placed and requires review and fulfillment. Please check the order and update the customer as needed.",
        cta_label="Open invoice",
        cta_url=invoice_url,
        items=order.get("items", []),
        settings=settings,
    )
    return _send_generic_email(settings, recipient, subject, body, html_body)


def _send_generic_email(settings: Settings, recipient: str, subject: str, body: str, html_body: str | None = None) -> tuple[bool, str | None]:
    backend = settings.email_delivery_backend

    if backend == "disabled":
        return False, "Email delivery backend is disabled"

    if backend == "console":
        print(f"[ORDER][EMAIL] to={recipient} subject={subject}\n{body}")
        return True, None

    if backend == "smtp":
        if not settings.smtp_host or not settings.smtp_from_email:
            logger.warning("SMTP backend selected but SMTP_HOST/SMTP_FROM_EMAIL is missing")
            return False, "SMTP backend is missing SMTP_HOST or SMTP_FROM_EMAIL"

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return True, None
        except Exception as exc:
            logger.warning("SMTP order email failed for %s: %s", recipient, exc)
            return False, f"SMTP send failed: {exc}"

    if backend == "ses":
        source_email = settings.ses_from_email or settings.smtp_from_email
        if not source_email:
            logger.warning("SES backend selected but SES_FROM_EMAIL is missing")
            return False, "SES backend is missing SES_FROM_EMAIL"

        try:
            client = boto3.client("ses", region_name=settings.aws_region)
            payload = {
                "Source": source_email,
                "Destination": {"ToAddresses": [recipient]},
                "Message": {
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}, **({"Html": {"Data": html_body}} if html_body else {})},
                },
            }
            if settings.ses_configuration_set:
                payload["ConfigurationSetName"] = settings.ses_configuration_set

            client.send_email(**payload)
            return True, None
        except Exception as exc:
            logger.warning("SES order email failed for %s: %s", recipient, exc)
            return False, f"SES send failed: {exc}"

    return False, f"Unsupported email backend: {backend}"


def send_email_verification_code_detailed(settings: Settings, recipient: str, code: str) -> tuple[bool, str | None]:
    backend = settings.email_delivery_backend

    if backend == "disabled":
        return False, "Email delivery backend is disabled"

    if backend == "console":
        print(f"[OTP][EMAIL] to={recipient} code={code}")
        return True, None

    if backend == "smtp":
        if not settings.smtp_host or not settings.smtp_from_email:
            logger.warning("SMTP backend selected but SMTP_HOST/SMTP_FROM_EMAIL is missing")
            return False, "SMTP backend is missing SMTP_HOST or SMTP_FROM_EMAIL"

        message = EmailMessage()
        message["Subject"] = "Your Divine Reesha verification code"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(f"Your verification code is: {code}. It expires soon.")

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return True, None
        except Exception as exc:
            logger.warning("SMTP OTP email send failed: %s", exc)
            return False, f"SMTP send failed: {exc}"

    if backend == "ses":
        source_email = settings.ses_from_email or settings.smtp_from_email
        if not source_email:
            logger.warning("SES backend selected but SES_FROM_EMAIL is missing")
            return False, "SES backend is missing SES_FROM_EMAIL"

        try:
            client = boto3.client("ses", region_name=settings.aws_region)
            payload = {
                "Source": source_email,
                "Destination": {"ToAddresses": [recipient]},
                "Message": {
                    "Subject": {"Data": "Your Divine Reesha verification code"},
                    "Body": {
                        "Text": {"Data": f"Your verification code is: {code}. It expires soon."},
                    },
                },
            }
            if settings.ses_configuration_set:
                payload["ConfigurationSetName"] = settings.ses_configuration_set

            client.send_email(**payload)
            return True, None
        except Exception as exc:
            logger.warning("SES OTP email send failed: %s", exc)
            return False, f"SES send failed: {exc}"

    return False, f"Unsupported email backend: {backend}"


async def send_sms_verification_code(settings: Settings, phone: str, code: str) -> bool:
    success, _ = await send_sms_verification_code_detailed(settings, phone, code)
    return success


async def send_sms_verification_code_detailed(settings: Settings, phone: str, code: str) -> tuple[bool, str | None]:
    backend = settings.sms_delivery_backend

    if backend == "disabled":
        return False, "SMS delivery backend is disabled"

    if backend == "console":
        print(f"[OTP][SMS] to={phone} code={code}")
        return True, None

    if backend == "webhook":
        if not settings.sms_webhook_url:
            logger.warning("SMS webhook backend selected but SMS_WEBHOOK_URL is missing")
            return False, "SMS webhook backend is missing SMS_WEBHOOK_URL"

        headers = {"Content-Type": "application/json"}
        if settings.sms_webhook_auth_token:
            headers["Authorization"] = f"Bearer {settings.sms_webhook_auth_token}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    settings.sms_webhook_url,
                    json={"phone": phone, "message": f"Your Divine Reesha verification code is {code}."},
                    headers=headers,
                )
            if response.status_code < 300:
                return True, None
            return False, f"SMS webhook returned {response.status_code}"
        except Exception as exc:
            logger.warning("SMS webhook OTP send failed: %s", exc)
            return False, f"SMS webhook send failed: {exc}"

    return False, f"Unsupported SMS backend: {backend}"
