"""Tests for all /auth/* endpoints."""

import pytest
import app.routes.auth as auth_route


# ─── register ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_customer_success(client):
    payload = {
        "email": "new_customer@test.com",
        "password": "Password@123",
        "full_name": "New Customer",
        "role": "customer",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == payload["email"]
    assert data["user"]["role"] == "customer"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]


@pytest.mark.asyncio
async def test_register_vendor_pending(client):
    payload = {
        "email": "new_vendor@test.com",
        "password": "Password@123",
        "full_name": "New Vendor",
        "role": "vendor",
        "store_name": "New Vendor Store",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "vendor"
    assert data["user"]["status"] == "pending"
    assert data["tokens"] is None


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {
        "email": "new_customer@test.com",
        "password": "Password@123",
        "role": "customer",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_password_too_short(client):
    response = await client.post("/auth/register", json={
        "email": "short_pw@test.com",
        "password": "abc",
        "role": "customer",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_alias_customer_success(client):
    payload = {
        "email": "signup_alias_customer@test.com",
        "password": "Password@123",
        "full_name": "Signup Alias Customer",
        "role": "customer",
    }
    response = await client.post("/auth/signup", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == payload["email"]
    assert data["user"]["role"] == "customer"
    assert data["tokens"]["access_token"]


@pytest.mark.asyncio
async def test_signup_with_email_and_mobile_verification_success(client):
    auth_route.settings.otp_expose_codes = True
    initiate = await client.post(
        "/auth/signup/initiate",
        json={
            "email": "otp_customer@test.com",
            "password": "Password@123",
            "full_name": "OTP Customer",
            "phone": "+91-9000011111",
            "role": "customer",
        },
    )
    assert initiate.status_code == 200
    body = initiate.json()
    assert body["email_verification_code"]
    assert body["mobile_verification_code"]

    complete = await client.post(
        "/auth/signup/complete",
        json={
            "email": "otp_customer@test.com",
            "email_code": body["email_verification_code"],
            "mobile_code": body["mobile_verification_code"],
        },
    )
    assert complete.status_code == 201
    done = complete.json()
    assert done["user"]["email"] == "otp_customer@test.com"
    assert done["user"]["email_verified"] is True
    assert done["tokens"]["access_token"]


@pytest.mark.asyncio
async def test_signup_complete_invalid_mobile_code(client):
    auth_route.settings.otp_expose_codes = True
    initiate = await client.post(
        "/auth/signup/initiate",
        json={
            "email": "otp_invalid_mobile@test.com",
            "password": "Password@123",
            "phone": "+91-9000012222",
            "role": "customer",
        },
    )
    assert initiate.status_code == 200
    body = initiate.json()

    complete = await client.post(
        "/auth/signup/complete",
        json={
            "email": "otp_invalid_mobile@test.com",
            "email_code": body["email_verification_code"],
            "mobile_code": "000000",
        },
    )
    assert complete.status_code == 400


# ─── login ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client, customer_token):
    # customer_token fixture ensures customer@test.com exists in the test DB
    response = await client.post("/auth/login", json={
        "email": "customer@test.com",
        "password": "Customer@12345",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["tokens"]["access_token"]
    assert data["user"]["role"] == "customer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    response = await client.post("/auth/login", json={
        "email": "customer@test.com",
        "password": "WrongPass@123",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    response = await client.post("/auth/login", json={
        "email": "nobody@test.com",
        "password": "Password@123",
    })
    assert response.status_code == 401


# ─── profile ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_profile_authenticated(client, customer_token):
    response = await client.get(
        "/auth/profile",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "customer@test.com"
    assert data["role"] == "customer"


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client):
    response = await client.get("/auth/profile")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_profile(client, customer_token):
    response = await client.put(
        "/auth/profile",
        json={"full_name": "Updated Name", "bio": "Hello!"},
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Updated Name"
    assert data["bio"] == "Hello!"


# ─── refresh token ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token(client, test_db, customer_token):
    # Login first to get a fresh pair
    resp = await client.post("/auth/login", json={
        "email": "customer@test.com",
        "password": "Customer@12345",
    })
    assert resp.status_code == 200
    refresh_token = resp.json()["tokens"]["refresh_token"]

    response = await client.post("/auth/refresh-token", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_token_invalid(client):
    response = await client.post("/auth/refresh-token", json={"refresh_token": "totally-invalid-refresh-token-value-xyz"})
    assert response.status_code == 401


# ─── change password ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password_wrong_current(client, customer_token):
    response = await client.post(
        "/auth/change-password",
        json={"current_password": "WrongPass@123", "new_password": "NewPass@123"},
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_change_password_success(client, test_db):
    # Register a throwaway user so we can change their password safely
    reg = await client.post("/auth/register", json={
        "email": "chpw@test.com",
        "password": "OldPass@123",
        "role": "customer",
    })
    assert reg.status_code == 201
    token = reg.json()["tokens"]["access_token"]

    response = await client.post(
        "/auth/change-password",
        json={"current_password": "OldPass@123", "new_password": "NewPass@123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["message"]


# ─── forgot / reset password ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forgot_password_unknown_email(client):
    response = await client.post("/auth/forgot-password", json={"email": "nobody@test.com"})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_forgot_and_reset_password(client):
    # Register a throwaway user
    reg = await client.post("/auth/register", json={
        "email": "resetme@test.com",
        "password": "OldPass@123",
        "role": "customer",
    })
    assert reg.status_code == 201

    forgot_resp = await client.post("/auth/forgot-password", json={"email": "resetme@test.com"})
    assert forgot_resp.status_code == 200
    reset_token = forgot_resp.json().get("reset_token")
    assert reset_token

    reset_resp = await client.post("/auth/reset-password", json={
        "token": reset_token,
        "new_password": "NewPass@123",
    })
    assert reset_resp.status_code == 200
    assert reset_resp.json()["message"]

    # Second use of same token should fail
    resp2 = await client.post("/auth/reset-password", json={
        "token": reset_token,
        "new_password": "AnotherPass@123",
    })
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client):
    response = await client.post("/auth/reset-password", json={
        "token": "totally-fake-token-that-is-long-enough",
        "new_password": "NewPass@123",
    })
    assert response.status_code == 400


# ─── email verification ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_email_invalid_token(client):
    response = await client.post("/auth/verify-email", json={"token": "totally-fake-verification-token-long"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_resend_verification_unknown_email(client):
    response = await client.post("/auth/resend-verification", json={"email": "nobody@test.com"})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_resend_and_verify_email(client):
    reg = await client.post("/auth/register", json={
        "email": "verifytest@test.com",
        "password": "Pass@12345",
        "role": "customer",
    })
    assert reg.status_code == 201

    resend_resp = await client.post("/auth/resend-verification", json={"email": "verifytest@test.com"})
    assert resend_resp.status_code == 200
    token = resend_resp.json().get("verification_token")
    assert token

    verify_resp = await client.post("/auth/verify-email", json={"token": token})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["message"]


# ─── logout ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout(client, customer_token):
    login = await client.post("/auth/login", json={
        "email": "customer@test.com",
        "password": "Customer@12345",
    })
    token = login.json()["tokens"]["access_token"]

    response = await client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # token should now be rejected
    profile = await client.get(
        "/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile.status_code == 401


@pytest.mark.asyncio
async def test_logout_unauthenticated(client):
    response = await client.post("/auth/logout")
    assert response.status_code == 401
