from datetime import UTC, datetime

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_products_state(test_db):
    await test_db.products.delete_many({})


@pytest.mark.asyncio
async def test_create_product_as_admin_with_image(client, admin_token):
    files = {
        "image": ("sample.jpg", b"fake-image-bytes", "image/jpeg"),
    }
    data = {
        "name": "Ocean Breeze Car Air Freshener",
        "category": "Air Fresheners",
        "subcategory": "Car Air Freshener",
        "brand": "Divine Reesha",
        "fragrance": "Ocean Breeze",
        "pack_size": "250 ml",
        "form": "Liquid",
        "usage": "Car",
        "price": "24.99",
        "stock": "100",
        "sku": "DR-OCB-01",
        "status": "Active",
    }

    response = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        data=data,
        files=files,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == data["name"]
    assert payload["category"] == data["category"]
    assert payload["price"] == 24.99
    assert payload["status"] == "Active"
    assert payload["image_url"] is not None
    assert "/media/products/" in payload["image_url"]


@pytest.mark.asyncio
async def test_create_product_requires_admin(client, customer_token):
    response = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {customer_token}"},
        data={"name": "Not Allowed", "category": "Air Fresheners"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_product_requires_auth(client):
    response = await client.post(
        "/products",
        data={"name": "No Auth", "category": "Air Fresheners"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_homepage_products_only_active_by_default(client, test_db):
    now = datetime.now(UTC)
    await test_db.products.insert_many(
        [
            {
                "name": "Visible Product",
                "category": "Air Fresheners",
                "price": 10,
                "stock": 5,
                "status": "Active",
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Hidden Draft",
                "category": "Air Fresheners",
                "price": 12,
                "stock": 5,
                "status": "Draft",
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    response = await client.get("/products")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "Visible Product"


@pytest.mark.asyncio
async def test_list_products_by_status(client, test_db):
    now = datetime.now(UTC)
    await test_db.products.insert_many(
        [
            {
                "name": "Archived Product",
                "category": "Air Fresheners",
                "price": 10,
                "stock": 5,
                "status": "Archived",
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Active Product",
                "category": "Air Fresheners",
                "price": 11,
                "stock": 6,
                "status": "Active",
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    response = await client.get("/products", params={"status": "Archived"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["status"] == "Archived"


@pytest.mark.asyncio
async def test_update_product_as_admin(client, admin_token):
    create_resp = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={
            "name": "Original Product",
            "category": "Air Fresheners",
            "price": "9.99",
            "stock": "10",
            "status": "Draft",
        },
    )
    assert create_resp.status_code == 201
    product_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/products/{product_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={
            "name": "Updated Product",
            "price": "19.50",
            "stock": "25",
            "status": "Active",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Updated Product"
    assert updated["price"] == 19.5
    assert updated["stock"] == 25
    assert updated["status"] == "Active"


@pytest.mark.asyncio
async def test_update_product_requires_admin(client, admin_token, customer_token):
    create_resp = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"name": "Admin Product", "category": "Air Fresheners"},
    )
    product_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/products/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
        data={"name": "Not Allowed"},
    )
    assert update_resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_product_as_admin(client, admin_token):
    create_resp = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"name": "Delete Me", "category": "Air Fresheners"},
    )
    product_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/products/{product_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/products/{product_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_product_requires_admin(client, admin_token, customer_token):
    create_resp = await client.post(
        "/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"name": "Protected", "category": "Air Fresheners"},
    )
    product_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/products/{product_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert delete_resp.status_code == 403
