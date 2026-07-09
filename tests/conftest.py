"""
Shared pytest fixtures for all test modules.

A throw-away MongoDB database (divine_reesha_test) is created before the
test session and dropped afterwards, so tests never touch production data.

All fixtures and tests MUST run in the same session-level event loop:
  - fixtures use loop_scope="session"
  - test files must declare:  pytestmark = pytest.mark.asyncio(loop_scope="session")
"""

import inspect

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.config import get_settings
from app.database import connect_to_mongo
from app.security import hash_password, generate_token_pair, hash_token
from datetime import UTC, datetime, timedelta


TEST_DB_NAME = "divine_reesha_test"


def pytest_collection_modifyitems(items):
    """Force every async test to run in the session event loop."""
    session_marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if isinstance(item, pytest.Function) and inspect.iscoroutinefunction(item.function):
            item.add_marker(session_marker, append=False)


# ─── mongo client & test db ──────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mongo_client():
    settings = get_settings()
    client = await connect_to_mongo(settings)
    # Drop any leftover data from a previous run
    await client.drop_database(TEST_DB_NAME)
    yield client
    await client.drop_database(TEST_DB_NAME)
    client.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_db(mongo_client):
    return mongo_client[TEST_DB_NAME]


# ─── HTTP client ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(test_db, mongo_client):
    """Async HTTPX client wired to the FastAPI app with the test database."""
    app.state.mongo_client = mongo_client
    app.state.mongo_db = test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── helpers ─────────────────────────────────────────────────────────────────

async def _create_user(db, email: str, password: str, role: str, status: str = "active") -> dict:
    existing = await db.users.find_one({"email": email})
    if existing:
        return existing
    salt, pw_hash = hash_password(password)
    now = datetime.now(UTC)
    document = {
        "email": email,
        "password_salt": salt,
        "password_hash": pw_hash,
        "full_name": f"{role.capitalize()} User",
        "phone": None,
        "avatar_url": None,
        "bio": None,
        "store_name": "Test Store" if role == "vendor" else None,
        "role": role,
        "status": status,
        "email_verified": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.users.insert_one(document)
    return await db.users.find_one({"_id": result.inserted_id})


async def _create_session(db, user: dict) -> str:
    access_token, refresh_token = generate_token_pair()
    now = datetime.now(UTC)
    await db.sessions.insert_one({
        "user_id": user["_id"],
        "role": user["role"],
        "access_token_hash": hash_token(access_token),
        "refresh_token_hash": hash_token(refresh_token),
        "created_at": now,
        "access_expires_at": now + timedelta(hours=24),
        "refresh_expires_at": now + timedelta(days=30),
        "revoked_at": None,
    })
    return access_token


# ─── per-role fixtures ────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_token(test_db) -> str:
    user = await _create_user(test_db, "admin@test.com", "Admin@12345", "admin")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def customer_token(test_db) -> str:
    user = await _create_user(test_db, "customer@test.com", "Customer@12345", "customer")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def vendor_token(test_db) -> str:
    user = await _create_user(test_db, "vendor@test.com", "Vendor@12345", "vendor")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_user(test_db) -> dict:
    return await _create_user(test_db, "admin@test.com", "Admin@12345", "admin")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def customer_user(test_db) -> dict:
    return await _create_user(test_db, "customer@test.com", "Customer@12345", "customer")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_db(mongo_client):
    return mongo_client[TEST_DB_NAME]


# ─── HTTP client (ASGI transport, no real network) ────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(test_db, mongo_client):
    """Async HTTPX client wired to the FastAPI app with the test database."""
    app.state.mongo_client = mongo_client
    app.state.mongo_db = test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── helpers ─────────────────────────────────────────────────────────────────

async def _create_user(db, email: str, password: str, role: str, status: str = "active") -> dict:
    """Insert a user directly into the test DB and return the document."""
    existing = await db.users.find_one({"email": email})
    if existing:
        return existing
    salt, pw_hash = hash_password(password)
    now = datetime.now(UTC)
    document = {
        "email": email,
        "password_salt": salt,
        "password_hash": pw_hash,
        "full_name": f"{role.capitalize()} User",
        "phone": None,
        "avatar_url": None,
        "bio": None,
        "store_name": "Test Store" if role == "vendor" else None,
        "role": role,
        "status": status,
        "email_verified": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.users.insert_one(document)
    return await db.users.find_one({"_id": result.inserted_id})


async def _create_session(db, user: dict) -> str:
    """Create a live session for a user and return the raw access token."""
    access_token, refresh_token = generate_token_pair()
    now = datetime.now(UTC)
    await db.sessions.insert_one({
        "user_id": user["_id"],
        "role": user["role"],
        "access_token_hash": hash_token(access_token),
        "refresh_token_hash": hash_token(refresh_token),
        "created_at": now,
        "access_expires_at": now + timedelta(hours=24),
        "refresh_expires_at": now + timedelta(days=30),
        "revoked_at": None,
    })
    return access_token


# ─── per-role fixtures ────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_token(test_db) -> str:
    user = await _create_user(test_db, "admin@test.com", "Admin@12345", "admin")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def customer_token(test_db) -> str:
    user = await _create_user(test_db, "customer@test.com", "Customer@12345", "customer")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def vendor_token(test_db) -> str:
    user = await _create_user(test_db, "vendor@test.com", "Vendor@12345", "vendor")
    return await _create_session(test_db, user)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_user(test_db) -> dict:
    return await _create_user(test_db, "admin@test.com", "Admin@12345", "admin")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def customer_user(test_db) -> dict:
    return await _create_user(test_db, "customer@test.com", "Customer@12345", "customer")
