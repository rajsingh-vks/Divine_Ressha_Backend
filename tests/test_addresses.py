import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_addresses_state(test_db):
    await test_db.addresses.delete_many({})


@pytest.mark.asyncio
async def test_create_and_list_addresses(client, customer_token):
    payload = {
        "full_name": "John Doe",
        "phone": "+1-555-222-1111",
        "line1": "221B Baker Street",
        "line2": "Near Central Park",
        "city": "London",
        "state": "Greater London",
        "postal_code": "NW1",
        "country": "UK",
        "address_type": "home",
        "is_default": True,
    }

    create_resp = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json=payload,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["full_name"] == "John Doe"
    assert body["is_default"] is True

    list_resp = await client.get(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["city"] == "London"


@pytest.mark.asyncio
async def test_update_address_and_set_default(client, customer_token):
    a1 = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "A One",
            "phone": "+1-555-111-0001",
            "line1": "Line 1",
            "city": "City A",
            "state": "State A",
            "postal_code": "10001",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    a2 = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "A Two",
            "phone": "+1-555-111-0002",
            "line1": "Line 2",
            "city": "City B",
            "state": "State B",
            "postal_code": "10002",
            "country": "US",
            "address_type": "office",
            "is_default": False,
        },
    )
    id1 = a1.json()["id"]
    id2 = a2.json()["id"]

    upd = await client.put(
        f"/addresses/{id1}",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"city": "Updated City"},
    )
    assert upd.status_code == 200
    assert upd.json()["city"] == "Updated City"

    make_default = await client.patch(
        f"/addresses/{id2}/default",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert make_default.status_code == 200
    assert make_default.json()["is_default"] is True

    all_items = await client.get(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    items = all_items.json()
    assert len(items) == 2
    assert items[0]["id"] == id2
    assert items[0]["is_default"] is True


@pytest.mark.asyncio
async def test_delete_address(client, customer_token):
    created = await client.post(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "full_name": "Delete User",
            "phone": "+1-555-111-3333",
            "line1": "Delete Line",
            "city": "Delete City",
            "state": "Delete State",
            "postal_code": "10003",
            "country": "US",
            "address_type": "home",
            "is_default": True,
        },
    )
    address_id = created.json()["id"]

    delete_resp = await client.delete(
        f"/addresses/{address_id}",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert delete_resp.status_code == 204

    list_resp = await client.get(
        "/addresses",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_addresses_require_auth(client):
    response = await client.get("/addresses")
    assert response.status_code == 401
