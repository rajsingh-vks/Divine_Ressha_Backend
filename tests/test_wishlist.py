from datetime import UTC, datetime

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_wishlist_state(test_db):
    await test_db.wishlist.delete_many({})
    await test_db.products.delete_many({})


async def _create_product(test_db, name: str = "Wishlist Product") -> str:
    now = datetime.now(UTC)
    result = await test_db.products.insert_one(
        {
            "name": name,
            "category": "Air Fresheners",
            "subcategory": "Car Air Freshener",
            "brand": "Divine Reesha",
            "price": 199.0,
            "image_url": "https://example.com/p1.jpg",
            "created_at": now,
            "updated_at": now,
        }
    )
    return str(result.inserted_id)


@pytest.mark.asyncio
async def test_get_wishlist_empty(client, customer_token):
    response = await client.get(
        "/wishlist",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_add_to_wishlist(client, customer_token, test_db):
    product_id = await _create_product(test_db)
    response = await client.post(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["product"]["id"] == product_id


@pytest.mark.asyncio
async def test_add_to_wishlist_duplicate_is_idempotent(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Wish Duplicate")
    first = await client.post(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    second = await client.post(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_get_wishlist_with_items(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Wish List View")
    await client.post(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )

    response = await client.get(
        "/wishlist",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["product"]["id"] == product_id


@pytest.mark.asyncio
async def test_remove_from_wishlist(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Wish Remove")
    await client.post(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )

    delete_resp = await client.delete(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert delete_resp.status_code == 204

    list_resp = await client.get(
        "/wishlist",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_remove_from_wishlist_not_found(client, customer_token, test_db):
    product_id = await _create_product(test_db, name="Wish Missing")
    response = await client.delete(
        f"/wishlist/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_wishlist_requires_auth(client, test_db):
    product_id = await _create_product(test_db, name="Wish Auth")
    response = await client.post(f"/wishlist/{product_id}")
    assert response.status_code == 401
