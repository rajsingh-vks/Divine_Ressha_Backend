from bson import ObjectId
import pytest


async def _create_product(test_db, name: str = "Review Product", price: float = 199.0) -> str:
    result = await test_db.products.insert_one(
        {
            "name": name,
            "category": "Skin Care",
            "brand": "Divine Reesha",
            "price": price,
            "stock": 10,
            "status": "Active",
            "images": [],
            "created_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
        }
    )
    return str(result.inserted_id)


async def _create_delivered_order(client, customer_token, test_db, product_id: str, status: str = "delivered"):
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Review User",
            "phone": "+1-555-101-2020",
            "line1": "Review Address",
            "city": "Mumbai",
            "state": "MH",
            "postal_code": "400001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    assert address.status_code == 201

    await client.delete(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
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
    assert created.status_code == 201
    order_id = created.json()["id"]

    await test_db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": status, "payment_status": "paid"}},
    )

    return order_id


@pytest.mark.asyncio
async def test_submit_review_for_delivered_order(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Rose Serum")
    order_id = await _create_delivered_order(client, customer_token, test_db, product_id)

    response = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "product_id": product_id,
            "order_id": order_id,
            "rating": 5,
            "comment": "Excellent product and quick delivery.",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] == product_id
    assert body["rating"] == 5
    assert body["comment"] == "Excellent product and quick delivery."


@pytest.mark.asyncio
async def test_review_requires_delivery_and_purchase(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Coconut Oil")
    address = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Review User",
            "phone": "+1-555-111-2222",
            "line1": "No Review Address",
            "city": "Pune",
            "state": "MH",
            "postal_code": "411001",
            "country": "IN",
            "address_type": "home",
            "is_default": True,
        },
    )
    assert address.status_code == 201

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
    assert created.status_code == 201
    order_id = created.json()["id"]

    before_delivery = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "order_id": order_id, "rating": 4, "comment": "Too soon"},
    )
    assert before_delivery.status_code == 400

    other_product_id = await _create_product(test_db, name="Different Product")
    another_order = await _create_delivered_order(client, customer_token, test_db, other_product_id)
    not_purchased = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "order_id": another_order, "rating": 3, "comment": "Not purchased"},
    )
    assert not_purchased.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_review_is_rejected_and_update_allowed(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Night Cream")
    order_id = await _create_delivered_order(client, customer_token, test_db, product_id)

    create = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "order_id": order_id, "rating": 5, "comment": "Original review."},
    )
    assert create.status_code == 201
    review_id = create.json()["id"]

    duplicate = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "order_id": order_id, "rating": 4, "comment": "Duplicate."},
    )
    assert duplicate.status_code == 409

    update = await client.put(
        f"/reviews/{review_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"rating": 4, "comment": "Updated review."},
    )
    assert update.status_code == 200
    assert update.json()["comment"] == "Updated review."


@pytest.mark.asyncio
async def test_product_and_my_reviews_are_listed(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Saffron Mist")
    order_id = await _create_delivered_order(client, customer_token, test_db, product_id)

    review = await client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "order_id": order_id, "rating": 3, "comment": "Good but not great."},
    )
    assert review.status_code == 201

    product_reviews = await client.get(f"/products/{product_id}/reviews")
    assert product_reviews.status_code == 200
    assert len(product_reviews.json()) >= 1

    my_reviews = await client.get("/reviews/me", headers={"Authorization": f"Bearer {customer_token}"})
    assert my_reviews.status_code == 200
    assert len(my_reviews.json()) >= 1

    delete_resp = await client.delete(
        f"/reviews/{review.json()['id']}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert delete_resp.status_code == 204
