from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import boto3
import httpx

from app.config import Settings


logger = logging.getLogger(__name__)


def send_email_verification_code(settings: Settings, recipient: str, code: str) -> bool:
    success, _ = send_email_verification_code_detailed(settings, recipient, code)
    return success


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
