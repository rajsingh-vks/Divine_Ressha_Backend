import pytest

import app.routes.aws_sns as aws_sns_route


@pytest.mark.asyncio
async def test_sns_subscription_confirmation(client, monkeypatch):
    called = {"value": False, "url": None}

    class _FakeResponse:
        status_code = 200

    def _fake_get(url: str, timeout: int):
        called["value"] = True
        called["url"] = url
        assert timeout == 10
        return _FakeResponse()

    monkeypatch.setattr(aws_sns_route.requests, "get", _fake_get)

    resp = await client.post(
        "/api/v1/aws/sns",
        headers={"x-amz-sns-message-type": "SubscriptionConfirmation"},
        json={
            "Type": "SubscriptionConfirmation",
            "SubscribeURL": "https://sns.ap-south-1.amazonaws.com/confirm",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert called["value"] is True
    assert called["url"] == "https://sns.ap-south-1.amazonaws.com/confirm"


@pytest.mark.asyncio
async def test_sns_notification_returns_ok(client):
    resp = await client.post(
        "/api/v1/aws/sns",
        headers={"x-amz-sns-message-type": "Notification"},
        json={
            "Type": "Notification",
            "Message": '{"notificationType":"Bounce","bounce":{"bouncedRecipients":[{"emailAddress":"bounce_user@test.com"}]}}',
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
