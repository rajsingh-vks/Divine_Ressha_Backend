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
        print("SNS Notification received")
        print(body)

    return {"status": "ok"}
