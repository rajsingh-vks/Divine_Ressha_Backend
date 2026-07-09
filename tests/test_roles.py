"""Tests for /roles/* and /permissions endpoints."""

import pytest


# ─── permissions catalog ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_permissions_public(client):
    response = await client.get("/permissions")
    assert response.status_code == 200
    data = response.json()
    assert "permissions" in data
    assert "default_roles" in data
    assert len(data["permissions"]) > 0
    codes = [p["code"] for p in data["permissions"]]
    assert "profile.manage" in codes
    assert "users.manage" in codes


@pytest.mark.asyncio
async def test_permissions_contain_all_three_default_roles(client):
    response = await client.get("/permissions")
    data = response.json()
    role_names = [r["name"] for r in data["default_roles"]]
    assert "customer" in role_names
    assert "vendor" in role_names
    assert "admin" in role_names


# ─── list roles ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_roles_as_admin(client, admin_token):
    response = await client.get(
        "/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_roles_as_customer_forbidden(client, customer_token):
    response = await client.get(
        "/roles",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_roles_unauthenticated(client):
    response = await client.get("/roles")
    assert response.status_code == 401


# ─── create role ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_role_success(client, admin_token):
    response = await client.post(
        "/roles",
        json={
            "name": "marketing",
            "description": "Marketing team role",
            "permissions": ["reports.view", "coupons.manage"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "marketing"
    assert "reports.view" in data["permissions"]
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_create_role_invalid_permission(client, admin_token):
    response = await client.post(
        "/roles",
        json={
            "name": "brokrole",
            "permissions": ["nonexistent.permission"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_role_name_too_short(client, admin_token):
    response = await client.post(
        "/roles",
        json={"name": "x", "permissions": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_role_unauthenticated(client):
    response = await client.post(
        "/roles",
        json={"name": "sneaky", "permissions": []},
    )
    assert response.status_code == 401


# ─── update role ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_role_success(client, admin_token):
    # Create a role first
    create_resp = await client.post(
        "/roles",
        json={"name": "updateme", "permissions": ["reports.view"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["id"]

    response = await client.put(
        f"/roles/{role_id}",
        json={"description": "Updated description", "permissions": ["coupons.manage"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "Updated description"
    assert "coupons.manage" in data["permissions"]


@pytest.mark.asyncio
async def test_update_role_not_found(client, admin_token):
    response = await client.put(
        "/roles/000000000000000000000000",
        json={"description": "Ghost"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_role_invalid_permission(client, admin_token):
    create_resp = await client.post(
        "/roles",
        json={"name": "anothertestupdaterole", "permissions": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["id"]

    response = await client.put(
        f"/roles/{role_id}",
        json={"permissions": ["fake.permission"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


# ─── update role permissions ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_role_permissions(client, admin_token):
    create_resp = await client.post(
        "/roles",
        json={"name": "permtesrole", "permissions": ["reports.view"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["id"]

    response = await client.put(
        f"/roles/{role_id}/permissions",
        json={"permissions": ["orders.view", "payouts.view"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "orders.view" in data["permissions"]
    assert "payouts.view" in data["permissions"]


@pytest.mark.asyncio
async def test_update_role_permissions_not_found(client, admin_token):
    response = await client.put(
        "/roles/000000000000000000000000/permissions",
        json={"permissions": ["reports.view"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_role_permissions_invalid(client, admin_token):
    create_resp = await client.post(
        "/roles",
        json={"name": "invpermrole", "permissions": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["id"]

    response = await client.put(
        f"/roles/{role_id}/permissions",
        json={"permissions": ["totally.fake"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


# ─── delete role ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_role_success(client, admin_token):
    create_resp = await client.post(
        "/roles",
        json={"name": "tobedeleted", "permissions": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["id"]

    response = await client.delete(
        f"/roles/{role_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_role_not_found(client, admin_token):
    response = await client.delete(
        "/roles/000000000000000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_role_unauthenticated(client):
    response = await client.delete("/roles/000000000000000000000000")
    assert response.status_code == 401
