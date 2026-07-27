import json
import requests
from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/v1/aws", tags=["AWS SNS"])


@router.post("/sns")
async def sns_webhook(request: Request):
    body = await request.json()

    print("===== SNS MESSAGE =====")
    print(json.dumps(body, indent=2))

    message_type = request.headers.get("x-amz-sns-message-type")

    if message_type == "SubscriptionConfirmation":
        subscribe_url = body["SubscribeURL"]
        response = requests.get(subscribe_url, timeout=10)
        print(f"Subscription confirmed: {response.status_code}")

    elif message_type == "Notification":
        message = json.loads(body["Message"])

        print("===== SES EVENT =====")
        print(json.dumps(message, indent=2))

        event_type = message.get("notificationType") or message.get("eventType")
        print(f"Event: {event_type}")

        if event_type == "Bounce":
            print("Handle bounced email")

        elif event_type == "Complaint":
            print("Handle spam complaint")

        elif event_type == "Delivery":
            print("Email delivered successfully")

        elif event_type == "AmazonSnsSubscriptionSucceeded":
            print("SES successfully connected to SNS")

        print("SNS Notification received")
        print(body)

    return {"status": "ok"}
