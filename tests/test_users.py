"""Tests for /users/* endpoints (admin only)."""

import pytest


# ─── list users ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users_as_admin(client, admin_token):
    response = await client.get(
        "/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_users_as_customer_forbidden(client, customer_token):
    response = await client.get(
        "/users",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_unauthenticated(client):
    response = await client.get("/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_users_filter_by_role(client, admin_token):
    response = await client.get(
        "/users?role=customer",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert all(u["role"] == "customer" for u in data)


@pytest.mark.asyncio
async def test_list_users_pagination(client, admin_token):
    response = await client.get(
        "/users?limit=1&skip=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) <= 1


# ─── get user by id ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_as_admin(client, admin_token, customer_user):
    user_id = str(customer_user["_id"])
    response = await client.get(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == user_id


@pytest.mark.asyncio
async def test_get_user_not_found(client, admin_token):
    response = await client.get(
        "/users/000000000000000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_user_invalid_id(client, admin_token):
    response = await client.get(
        "/users/invalid-id",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


# ─── update user ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_as_admin(client, admin_token, customer_user):
    user_id = str(customer_user["_id"])
    response = await client.put(
        f"/users/{user_id}",
        json={"full_name": "Admin Updated"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Admin Updated"


@pytest.mark.asyncio
async def test_update_user_not_found(client, admin_token):
    response = await client.put(
        "/users/000000000000000000000000",
        json={"full_name": "Ghost"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


# ─── update user status ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_status_suspended(client, admin_token, customer_user):
    user_id = str(customer_user["_id"])
    response = await client.patch(
        f"/users/{user_id}/status",
        json={"status": "suspended"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


@pytest.mark.asyncio
async def test_update_user_status_reactivate(client, admin_token, customer_user):
    user_id = str(customer_user["_id"])
    response = await client.patch(
        f"/users/{user_id}/status",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_update_user_status_invalid_value(client, admin_token, customer_user):
    user_id = str(customer_user["_id"])
    response = await client.patch(
        f"/users/{user_id}/status",
        json={"status": "unknown_status"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422


# ─── delete user ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user_as_admin(client, admin_token, test_db):
    # Register a throwaway user to delete
    reg = await client.post("/auth/register", json={
        "email": "todelete@test.com",
        "password": "Delete@12345",
        "role": "customer",
    })
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    response = await client.delete(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204

    # Soft-delete: status should now be "deleted" but record remains
    get_resp = await client.get(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_user_not_found(client, admin_token):
    response = await client.delete(
        "/users/000000000000000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_user_hard_delete(client, admin_token):
    reg = await client.post("/auth/register", json={
        "email": "harddelete@test.com",
        "password": "Delete@12345",
        "role": "customer",
    })
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    response = await client.delete(
        f"/users/{user_id}?hard=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204

    get_resp = await client.get(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_user_hard_delete_self_blocked(client, admin_token, admin_user):
    response = await client.delete(
        f"/users/{admin_user['_id']}?hard=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


# ─── create admin user (secure) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_admin_user_as_admin(client, admin_token):
    response = await client.post(
        "/users/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "newadmin@test.com",
            "password": "Admin@12345",
            "full_name": "New Admin",
            "phone": "+1-555-009-9999",
            "bio": "Created by admin",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newadmin@test.com"
    assert body["role"] == "admin"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_admin_user_forbidden_for_customer(client, customer_token):
    response = await client.post(
        "/users/admin",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "email": "blockedadmin@test.com",
            "password": "Admin@12345",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_admin_user_requires_auth(client):
    response = await client.post(
        "/users/admin",
        json={
            "email": "noauthadmin@test.com",
            "password": "Admin@12345",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_admin_user_conflict_email(client, admin_token):
    await client.post(
        "/users/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "dupeadmin@test.com",
            "password": "Admin@12345",
        },
    )
    response = await client.post(
        "/users/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "dupeadmin@test.com",
            "password": "Admin@12345",
        },
    )
    assert response.status_code == 409
