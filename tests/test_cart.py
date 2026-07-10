from datetime import UTC, datetime

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_cart_state(test_db):
    await test_db.cart.delete_many({})
    await test_db.products.delete_many({})


async def _create_product(test_db, name: str = "Cart Product", price: float = 299.0) -> str:
    now = datetime.now(UTC)
    result = await test_db.products.insert_one(
        {
            "name": name,
            "category": "Air Fresheners",
            "subcategory": "Car Air Freshener",
            "brand": "Divine Reesha",
            "price": price,
            "image_url": "https://example.com/p1.jpg",
            "created_at": now,
            "updated_at": now,
        }
    )
    return str(result.inserted_id)


@pytest.mark.asyncio
async def test_get_cart_empty(client, customer_token):
    response = await client.get(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total_items": 0, "subtotal": 0.0}


@pytest.mark.asyncio
async def test_add_to_cart(client, customer_token, test_db):
    product_id = await _create_product(test_db)

    response = await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 2},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_items"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["product"]["id"] == product_id
    assert data["items"][0]["line_total"] == 598.0


@pytest.mark.asyncio
async def test_add_to_cart_same_product_merges_quantity(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Cart Merge", price=100.0)

    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    response = await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 3},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_items"] == 4
    assert data["items"][0]["quantity"] == 4


@pytest.mark.asyncio
async def test_update_cart_item(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Cart Update", price=50.0)
    add_resp = await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 2},
    )
    item_id = add_resp.json()["items"][0]["id"]

    update_resp = await client.put(
        f"/cart/{item_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"quantity": 5},
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["items"][0]["quantity"] == 5
    assert body["subtotal"] == 250.0


@pytest.mark.asyncio
async def test_delete_cart_item(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Cart Delete", price=75.0)
    add_resp = await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": product_id, "quantity": 1},
    )
    item_id = add_resp.json()["items"][0]["id"]

    delete_resp = await client.delete(
        f"/cart/{item_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"items": [], "total_items": 0, "subtotal": 0.0}


@pytest.mark.asyncio
async def test_clear_cart(client, customer_token, test_db):
    p1 = await _create_product(test_db, name="Cart Clear 1", price=10.0)
    p2 = await _create_product(test_db, name="Cart Clear 2", price=20.0)

    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": p1, "quantity": 1},
    )
    await client.post(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"product_id": p2, "quantity": 2},
    )

    clear_resp = await client.delete(
        "/cart",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json() == {"items": [], "total_items": 0, "subtotal": 0.0}


@pytest.mark.asyncio
async def test_cart_item_not_found(client, customer_token):
    response = await client.put(
        "/cart/000000000000000000000000",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"quantity": 3},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cart_requires_auth(client, test_db):
    product_id = await _create_product(test_db, name="Cart Auth")
    response = await client.post("/cart", json={"product_id": product_id, "quantity": 1})
    assert response.status_code == 401
