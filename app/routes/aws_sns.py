from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Request, status


router = APIRouter(prefix="/api/v1/aws", tags=["AWS SNS"])


async def _confirm_subscription(subscribe_url: str) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(subscribe_url)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SNS subscription confirmation request failed.",
        )


def _safe_json_loads(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


@router.post("/sns")
async def sns_webhook(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid SNS payload.")

    message_type = body.get("Type")

    if message_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL")
        if not subscribe_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SubscribeURL missing in SNS payload.")
        await _confirm_subscription(subscribe_url)
        return {"status": "subscription_confirmed"}

    if message_type in {"Notification", "UnsubscribeConfirmation"}:
        now = datetime.now(UTC)
        db = request.app.state.mongo_db

        parsed_message = _safe_json_loads(body.get("Message"))
        if message_type == "UnsubscribeConfirmation":
            return {"status": "unsubscribe_confirmation_received"}

        if not parsed_message:
            await db.email_events.insert_one(
                {
                    "provider": "SES",
                    "event": "UNKNOWN",
                    "email": None,
                    "raw": body,
                    "created_at": now,
                }
            )
            return {"status": "ignored", "reason": "message_not_json"}

        notification_type = (parsed_message.get("notificationType") or "").strip()

        if notification_type == "Bounce":
            bounce = parsed_message.get("bounce") or {}
            recipients = bounce.get("bouncedRecipients") or []
            updated = 0
            for recipient in recipients:
                email = (recipient.get("emailAddress") or "").strip().lower()
                if not email:
                    continue

                await db.users.update_one(
                    {"email": email},
                    {"$set": {"email_status": "BOUNCED", "updated_at": now}},
                )
                await db.email_events.insert_one(
                    {
                        "provider": "SES",
                        "event": "BOUNCE",
                        "email": email,
                        "raw": parsed_message,
                        "created_at": now,
                    }
                )
                updated += 1

            return {"status": "bounce_processed", "recipients": updated}

        if notification_type == "Complaint":
            complaint = parsed_message.get("complaint") or {}
            recipients = complaint.get("complainedRecipients") or []
            updated = 0
            for recipient in recipients:
                email = (recipient.get("emailAddress") or "").strip().lower()
                if not email:
                    continue

                await db.users.update_one(
                    {"email": email},
                    {"$set": {"email_status": "COMPLAINED", "updated_at": now}},
                )
                await db.email_events.insert_one(
                    {
                        "provider": "SES",
                        "event": "COMPLAINT",
                        "email": email,
                        "raw": parsed_message,
                        "created_at": now,
                    }
                )
                updated += 1

            return {"status": "complaint_processed", "recipients": updated}

        await db.email_events.insert_one(
            {
                "provider": "SES",
                "event": notification_type or "UNKNOWN",
                "email": None,
                "raw": parsed_message,
                "created_at": now,
            }
        )
        return {"status": "ignored", "reason": "unsupported_notification_type"}

    return {"status": "ignored", "reason": "unsupported_sns_type"}
