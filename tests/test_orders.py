from datetime import UTC, datetime

import pytest
import pytest_asyncio
from bson import ObjectId


@pytest_asyncio.fixture(autouse=True)
async def _clean_orders_state(test_db):
    await test_db.orders.delete_many({})
    await test_db.addresses.delete_many({})
    await test_db.cart.delete_many({})
    await test_db.products.delete_many({})


async def _create_product(test_db, name: str = "Order Product", price: float = 99.0) -> str:
    now = datetime.now(UTC)
    result = await test_db.products.insert_one(
        {
            "name": name,
            "category": "Air Fresheners",
            "price": price,
            "stock": 20,
            "status": "Active",
            "image_url": "https://example.com/prod.jpg",
            "created_at": now,
            "updated_at": now,
        }
    )
    return str(result.inserted_id)


@pytest.mark.asyncio
async def test_place_order_from_cart(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Order Customer",
            "phone": "+1-555-000-1111",
            "line1": "Main Street 1",
            "city": "Austin",
            "state": "TX",
            "postal_code": "73301",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    assert address.status_code == 201
    address_id = address.json()["id"]

    product_id = await _create_product(test_db, price=120.0)
    add_cart = await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 2},
    )
    assert add_cart.status_code == 201

    place = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address_id, "notes": "Leave at door"},
    )
    assert place.status_code == 201
    order = place.json()
    assert order["status"] == "placed"
    assert order["subtotal"] == 240.0
    assert order["total_items"] == 2
    assert order["shipping_address"]["city"] == "Austin"

    cart_after = await client.get(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert cart_after.status_code == 200
    assert cart_after.json()["items"] == []


@pytest.mark.asyncio
async def test_get_orders_and_history(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "History User",
            "phone": "+1-555-121-2121",
            "line1": "Line",
            "city": "City",
            "state": "State",
            "postal_code": "11111",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=50.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )

    resp_list = await client.get(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1

    resp_hist = await client.get(
        "/orders/user/history",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp_hist.status_code == 200
    assert len(resp_hist.json()) == 1


@pytest.mark.asyncio
async def test_update_order_status_admin_only(client, customer_token, admin_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Admin Flow",
            "phone": "+1-555-999-0000",
            "line1": "Address 9",
            "city": "NYC",
            "state": "NY",
            "postal_code": "10010",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=89.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    forbidden = await client.patch(
        f"/orders/{order_id}/status",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"status": "processing"},
    )
    assert forbidden.status_code == 403

    allowed = await client.patch(
        f"/orders/{order_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "processing"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "processing"


@pytest.mark.asyncio
async def test_cancel_order(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Cancel User",
            "phone": "+1-555-777-8888",
            "line1": "Cancel Address",
            "city": "Miami",
            "state": "FL",
            "postal_code": "33010",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=30.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 2},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    cancel_resp = await client.patch(
        f"/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"reason": "Ordered by mistake"},
    )
    assert cancel_resp.status_code == 200
    body = cancel_resp.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Ordered by mistake"
    assert body["refund_status"] == "not_required"


@pytest.mark.asyncio
async def test_cancel_paid_order_marks_refund_pending(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Refund User",
            "phone": "+1-555-333-4444",
            "line1": "Refund Address",
            "city": "Mumbai",
            "state": "MH",
            "postal_code": "400001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=70.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    await test_db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"payment_status": "paid"}},
    )

    cancel_resp = await client.patch(
        f"/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"reason": "Need refund"},
    )
    assert cancel_resp.status_code == 200
    body = cancel_resp.json()
    assert body["refund_status"] == "pending"
    assert body["refund_amount"] == 70.0


@pytest.mark.asyncio
async def test_request_return_for_delivered_order(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Return User",
            "phone": "+1-555-221-4455",
            "line1": "Return Address",
            "city": "Chennai",
            "state": "TN",
            "postal_code": "600001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=55.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    await test_db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": "delivered", "payment_status": "paid"}},
    )

    return_resp = await client.post(
        f"/orders/{order_id}/return",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"reason": "Damaged item"},
    )
    assert return_resp.status_code == 200
    body = return_resp.json()
    assert body["return_status"] == "requested"
    assert body["refund_status"] == "pending"


@pytest.mark.asyncio
async def test_admin_process_refund(client, customer_token, admin_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Process Refund",
            "phone": "+1-555-100-2000",
            "line1": "Process Address",
            "city": "Kolkata",
            "state": "WB",
            "postal_code": "700001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=80.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    await test_db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {
            "$set": {
                "status": "cancelled",
                "payment_status": "paid",
                "refund_status": "pending",
                "refund_amount": 80.0,
            }
        },
    )

    refund_resp = await client.patch(
        f"/orders/{order_id}/refund",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "processed", "reason": "Refund done", "refund_reference": "rfnd_123"},
    )
    assert refund_resp.status_code == 200
    body = refund_resp.json()
    assert body["refund_status"] == "processed"
    assert body["refund_reference"] == "rfnd_123"


@pytest.mark.asyncio
async def test_get_order_refund_summary_admin(client, customer_token, admin_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Refund Summary",
            "phone": "+1-555-555-2222",
            "line1": "Summary Address",
            "city": "Pune",
            "state": "MH",
            "postal_code": "411001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=150.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    await test_db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {
            "$set": {
                "payment_status": "paid",
                "refund_status": "pending",
                "refund_amount": 150.0,
                "refund_reason": "Customer requested cancellation",
            }
        },
    )

    summary = await client.get(
        f"/orders/{order_id}/refund",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["order_id"] == order_id
    assert body["refund_status"] == "pending"
    assert body["refund_amount"] == 150.0
    assert body["order_number"].startswith("DR-")


@pytest.mark.asyncio
async def test_get_order_refund_summary_forbidden_for_customer(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Refund Customer",
            "phone": "+1-555-100-3333",
            "line1": "Cust Address",
            "city": "Delhi",
            "state": "DL",
            "postal_code": "110001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=42.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    summary = await client.get(
        f"/orders/{order_id}/refund",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert summary.status_code == 403


@pytest.mark.asyncio
async def test_confirm_order_as_customer(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Confirm User",
            "phone": "+1-555-321-7654",
            "line1": "Confirm Address",
            "city": "Jaipur",
            "state": "RJ",
            "postal_code": "302001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=90.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    confirm = await client.post(
        f"/orders/{order_id}/confirm",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "payment_status": "paid",
            "razorpay_order_id": "order_live_123",
            "razorpay_payment_id": "pay_live_123",
            "razorpay_signature": "sig_live_123",
            "note": "Razorpay verified",
        },
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["status"] == "confirmed"
    assert body["payment_status"] == "paid"

    stored = await test_db.orders.find_one({"_id": ObjectId(order_id)})
    assert stored["razorpay_order_id"] == "order_live_123"
    assert stored["razorpay_payment_id"] == "pay_live_123"
    assert stored["razorpay_signature"] == "sig_live_123"
    assert stored["payment_provider"] == "razorpay"
    assert stored["paid_at"] is not None


@pytest.mark.asyncio
async def test_get_order_invoice(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Invoice User",
            "phone": "+1-555-333-7777",
            "line1": "Invoice Address",
            "city": "Noida",
            "state": "UP",
            "postal_code": "201301",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=40.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 2},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    invoice = await client.get(
        f"/orders/{order_id}/invoice",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert invoice.status_code == 200
    body = invoice.json()
    assert body["order_id"] == order_id
    assert body["invoice_number"].startswith("INV-")
    assert "/invoices/" in body["invoice_url"]


@pytest.mark.asyncio
async def test_get_order_tracking_aliases(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Track User",
            "phone": "+1-555-888-6666",
            "line1": "Track Address",
            "city": "Surat",
            "state": "GJ",
            "postal_code": "395003",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=25.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    tracking = await client.get(
        f"/orders/{order_id}/tracking",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert tracking.status_code == 200
    assert tracking.json()["order_id"] == order_id

    track = await client.get(
        f"/orders/{order_id}/track",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert track.status_code == 200
    assert track.json()["order_number"].startswith("DR-")


@pytest.mark.asyncio
async def test_send_order_confirmation(client, customer_token, test_db):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Notify User",
            "phone": "+1-555-444-2121",
            "line1": "Notify Address",
            "city": "Lucknow",
            "state": "UP",
            "postal_code": "226001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    product_id = await _create_product(test_db, price=61.0)
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    created = await client.post(
        "/orders",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"address_id": address.json()["id"]},
    )
    order_id = created.json()["id"]

    send_resp = await client.post(
        f"/orders/{order_id}/send-confirmation",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "payment_status": "paid",
            "razorpay_order_id": "order_sync_001",
            "razorpay_payment_id": "pay_sync_001",
            "razorpay_signature": "sig_sync_001",
        },
    )
    assert send_resp.status_code == 200
    body = send_resp.json()
    assert body["success"] is True
    assert body["order_id"] == order_id
    assert "/invoices/" in body["invoice_url"]

    stored = await test_db.orders.find_one({"_id": ObjectId(order_id)})
    assert stored["payment_status"] == "paid"
    assert stored["razorpay_payment_id"] == "pay_sync_001"
    assert stored["confirmation_sent_at"] is not None
