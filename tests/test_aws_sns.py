from datetime import UTC, datetime

import pytest
import pytest_asyncio

import app.routes.aws_sns as aws_sns_route


@pytest_asyncio.fixture(autouse=True)
async def _clean_sns_state(test_db):
    await test_db.email_events.delete_many({})


@pytest.mark.asyncio
async def test_sns_subscription_confirmation(client, monkeypatch):
    called = {"value": False}

    async def _fake_confirm(url: str):
        called["value"] = True
        assert url.startswith("https://")

    monkeypatch.setattr(aws_sns_route, "_confirm_subscription", _fake_confirm)

    resp = await client.post(
        "/api/v1/aws/sns",
        json={
            "Type": "SubscriptionConfirmation",
            "SubscribeURL": "https://sns.ap-south-1.amazonaws.com/confirm",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "subscription_confirmed"
    assert called["value"] is True


@pytest.mark.asyncio
async def test_sns_bounce_updates_user_status(client, test_db):
    now = datetime.now(UTC)
    await test_db.users.insert_one(
        {
            "email": "bounce_user@test.com",
            "password_salt": "x",
            "password_hash": "y",
            "role": "customer",
            "status": "active",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        }
    )

    resp = await client.post(
        "/api/v1/aws/sns",
        json={
            "Type": "Notification",
            "Message": '{"notificationType":"Bounce","bounce":{"bouncedRecipients":[{"emailAddress":"bounce_user@test.com"}]}}',
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "bounce_processed"

    updated = await test_db.users.find_one({"email": "bounce_user@test.com"})
    assert updated["email_status"] == "BOUNCED"

    event = await test_db.email_events.find_one({"email": "bounce_user@test.com", "event": "BOUNCE"})
    assert event is not None


@pytest.mark.asyncio
async def test_sns_complaint_updates_user_status(client, test_db):
    now = datetime.now(UTC)
    await test_db.users.insert_one(
        {
            "email": "complaint_user@test.com",
            "password_salt": "x",
            "password_hash": "y",
            "role": "customer",
            "status": "active",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        }
    )

    resp = await client.post(
        "/api/v1/aws/sns",
        json={
            "Type": "Notification",
            "Message": '{"notificationType":"Complaint","complaint":{"complainedRecipients":[{"emailAddress":"complaint_user@test.com"}]}}',
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "complaint_processed"

    updated = await test_db.users.find_one({"email": "complaint_user@test.com"})
    assert updated["email_status"] == "COMPLAINED"

    event = await test_db.email_events.find_one({"email": "complaint_user@test.com", "event": "COMPLAINT"})
    assert event is not None
