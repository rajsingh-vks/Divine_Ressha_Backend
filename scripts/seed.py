"""
Seed script – inserts default admin, vendor, and customer accounts.

Usage:
    python -m scripts.seed
    python -m scripts.seed --drop      # wipe existing users first
"""

import asyncio
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.database import connect_to_mongo
from app.security import hash_password

SEED_USERS = [
    {
        "email": "admin@divinereesha.com",
        "password": "Admin@12345",
        "full_name": "Divine Reesha Admin",
        "phone": "+1-555-000-0001",
        "role": "admin",
        "status": "active",
        "email_verified": True,
        "bio": "Platform administrator.",
    },
    {
        "email": "vendor@divinereesha.com",
        "password": "Vendor@12345",
        "full_name": "Demo Vendor",
        "phone": "+1-555-000-0002",
        "store_name": "Demo Vendor Store",
        "role": "vendor",
        "status": "active",
        "email_verified": True,
        "bio": "Sample vendor account.",
    },
    {
        "email": "customer@divinereesha.com",
        "password": "Customer@12345",
        "full_name": "Demo Customer",
        "phone": "+1-555-000-0003",
        "role": "customer",
        "status": "active",
        "email_verified": True,
        "bio": "Sample customer account.",
    },
]


async def seed(drop: bool = False) -> None:
    settings = get_settings()
    client = await connect_to_mongo(settings)
    db = client[settings.mongodb_database]

    try:
        if drop:
            await db.users.delete_many({"email": {"$in": [u["email"] for u in SEED_USERS]}})
            print("  Dropped existing seed users.")

        now = datetime.now(UTC)
        inserted = 0
        skipped = 0

        for user_data in SEED_USERS:
            existing = await db.users.find_one({"email": user_data["email"]})
            if existing:
                print(f"  SKIP  {user_data['email']}  (already exists, use --drop to reset)")
                skipped += 1
                continue

            salt, pw_hash = hash_password(user_data["password"])
            document = {
                "email": user_data["email"],
                "password_salt": salt,
                "password_hash": pw_hash,
                "full_name": user_data.get("full_name"),
                "phone": user_data.get("phone"),
                "avatar_url": None,
                "bio": user_data.get("bio"),
                "store_name": user_data.get("store_name"),
                "role": user_data["role"],
                "status": user_data["status"],
                "email_verified": user_data["email_verified"],
                "created_at": now,
                "updated_at": now,
            }
            result = await db.users.insert_one(document)
            print(f"  OK    {user_data['email']}  role={user_data['role']}  id={result.inserted_id}")
            inserted += 1

        print(f"\nDone. {inserted} inserted, {skipped} skipped.")

    finally:
        client.close()


if __name__ == "__main__":
    drop_flag = "--drop" in sys.argv
    asyncio.run(seed(drop=drop_flag))
