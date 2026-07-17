import hashlib
import hmac

import pytest

import app.routes.razorpay_checkout as checkout_route


@pytest.mark.asyncio
async def test_create_order_success(client, customer_token, monkeypatch):
    async def fake_create_order(payload: dict, key_id: str, key_secret: str) -> dict:
        return {
            "id": "order_test_123",
            "amount": payload["amount"],
            "currency": payload["currency"],
        }

    monkeypatch.setattr(checkout_route, "_call_razorpay_create_order", fake_create_order)
    monkeypatch.setattr(checkout_route.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(checkout_route.settings, "razorpay_key_secret", "secret_fake")

    response = await client.post(
        "/api/create-order",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"amount": 1500, "currency": "INR", "receipt": "rcpt-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == "order_test_123"
    assert body["amount"] == 1500
    assert body["currency"] == "INR"


@pytest.mark.asyncio
async def test_create_order_minimum_amount_validation(client, customer_token):
    response = await client.post(
        "/api/create-order",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"amount": 99, "currency": "INR", "receipt": "rcpt-low"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_verify_payment_success(client, customer_token, monkeypatch):
    secret = "test_secret"
    monkeypatch.setattr(checkout_route.settings, "razorpay_key_secret", secret)

    razorpay_order_id = "order_abc123"
    razorpay_payment_id = "pay_abc123"
    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/verify-payment",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": signature,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True


@pytest.mark.asyncio
async def test_verify_payment_signature_mismatch(client, customer_token, monkeypatch):
    monkeypatch.setattr(checkout_route.settings, "razorpay_key_secret", "test_secret")

    response = await client.post(
        "/api/verify-payment",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "razorpay_order_id": "order_abc123",
            "razorpay_payment_id": "pay_abc123",
            "razorpay_signature": "invalid_signature",
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_verify_payment_missing_fields(client, customer_token, monkeypatch):
    monkeypatch.setattr(checkout_route.settings, "razorpay_key_secret", "test_secret")

    response = await client.post(
        "/api/verify-payment",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"razorpay_order_id": "order_abc123"},
    )
    assert response.status_code == 400
