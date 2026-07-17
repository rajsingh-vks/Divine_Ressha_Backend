from datetime import UTC, datetime

import pytest
import pytest_asyncio

import app.routes.payments as payments_route


class _FakeRazorpayOrderAPI:
    def create(self, data: dict):
        return {
            "id": "order_test_123",
            "amount": data["amount"],
            "currency": data["currency"],
        }


class _FakeRazorpayUtility:
    def verify_payment_signature(self, data: dict):
        if data.get("razorpay_signature") != "valid_signature":
            raise ValueError("Invalid signature")
        return True


class _FakeRazorpayClient:
    def __init__(self, auth):
        self.auth = auth
        self.order = _FakeRazorpayOrderAPI()
        self.utility = _FakeRazorpayUtility()


@pytest_asyncio.fixture(autouse=True)
async def _clean_payments_state(test_db):
    await test_db.orders.delete_many({})
    await test_db.payments.delete_many({})


async def _insert_order_for_user(test_db, user_id) -> str:
    now = datetime.now(UTC)
    doc = {
        "user_id": user_id,
        "order_number": "DR-20260715-123456",
        "status": "placed",
        "items": [
            {
                "product_id": "p1",
                "name": "Test Product",
                "image_url": None,
                "unit_price": 199.0,
                "quantity": 2,
                "line_total": 398.0,
            }
        ],
        "shipping_address": {
            "full_name": "Test User",
            "phone": "+1-555-111-2222",
            "line1": "Addr line",
            "line2": None,
            "city": "City",
            "state": "State",
            "postal_code": "12345",
            "country": "IN",
            "address_type": "home",
        },
        "total_items": 2,
        "subtotal": 398.0,
        "notes": None,
        "cancel_reason": None,
        "cancelled_at": None,
        "status_history": [],
        "created_at": now,
        "updated_at": now,
    }
    res = await test_db.orders.insert_one(doc)
    return str(res.inserted_id)


@pytest.mark.asyncio
async def test_create_razorpay_order(client, customer_token, customer_user, test_db, monkeypatch):
    monkeypatch.setattr(payments_route.razorpay, "Client", _FakeRazorpayClient)
    monkeypatch.setattr(payments_route.settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(payments_route.settings, "razorpay_key_secret", "rzp_test_secret")
    monkeypatch.setattr(payments_route.settings, "razorpay_currency", "INR")

    order_id = await _insert_order_for_user(test_db, customer_user["_id"])

    response = await client.post(
        "/payments/razorpay/order",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"order_id": order_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key_id"] == "rzp_test_key"
    assert body["backend_order_id"] == order_id
    assert body["razorpay_order_id"] == "order_test_123"
    assert body["amount"] == 39800


@pytest.mark.asyncio
async def test_verify_razorpay_payment(client, customer_token, customer_user, test_db, monkeypatch):
    monkeypatch.setattr(payments_route.razorpay, "Client", _FakeRazorpayClient)
    monkeypatch.setattr(payments_route.settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(payments_route.settings, "razorpay_key_secret", "rzp_test_secret")
    monkeypatch.setattr(payments_route.settings, "razorpay_currency", "INR")

    order_id = await _insert_order_for_user(test_db, customer_user["_id"])

    create_resp = await client.post(
        "/payments/razorpay/order",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"order_id": order_id},
    )
    assert create_resp.status_code == 200

    verify_resp = await client.post(
        "/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "order_id": order_id,
            "razorpay_order_id": "order_test_123",
            "razorpay_payment_id": "pay_test_123",
            "razorpay_signature": "valid_signature",
        },
    )

    assert verify_resp.status_code == 200
    body = verify_resp.json()
    assert body["success"] is True
    assert body["backend_order_id"] == order_id
    assert body["payment_status"] == "paid"


@pytest.mark.asyncio
async def test_create_razorpay_order_requires_auth(client, customer_user, test_db, monkeypatch):
    monkeypatch.setattr(payments_route.razorpay, "Client", _FakeRazorpayClient)
    monkeypatch.setattr(payments_route.settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(payments_route.settings, "razorpay_key_secret", "rzp_test_secret")
    order_id = await _insert_order_for_user(test_db, customer_user["_id"])

    response = await client.post("/payments/razorpay/order", json={"order_id": order_id})
    assert response.status_code == 401
