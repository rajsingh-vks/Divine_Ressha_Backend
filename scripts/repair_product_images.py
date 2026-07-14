"""
Repair broken product image URLs for local media-backed images.

Usage:
    python -m scripts.repair_product_images           # dry-run
    python -m scripts.repair_product_images --apply   # write changes
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.database import connect_to_mongo


def _extract_relative_media_path(image_url: str | None) -> str | None:
    if not image_url:
        return None

    for prefix in ("/media/", "/api/media/"):
        if image_url.startswith(prefix):
            return image_url.removeprefix(prefix)

    if image_url.startswith("http://") or image_url.startswith("https://"):
        parsed = urlparse(image_url)
        for prefix in ("/media/", "/api/media/"):
            if parsed.path.startswith(prefix):
                return parsed.path.removeprefix(prefix)

    return None


async def repair(apply: bool = False) -> None:
    settings = get_settings()
    client = await connect_to_mongo(settings)
    db = client[settings.mongodb_database]

    media_root = Path(__file__).resolve().parents[1] / "media"
    checked = 0
    missing = 0

    try:
        cursor = db.products.find({"image_url": {"$type": "string", "$ne": ""}})
        async for product in cursor:
            checked += 1
            rel_path = _extract_relative_media_path(product.get("image_url"))
            if not rel_path:
                continue

            file_path = media_root / rel_path
            if file_path.exists():
                continue

            missing += 1
            print(f"MISSING  id={product['_id']}  image_url={product.get('image_url')}")

            if apply:
                await db.products.update_one(
                    {"_id": product["_id"]},
                    {
                        "$set": {
                            "image_url": None,
                            "updated_at": datetime.now(UTC),
                        }
                    },
                )

        mode = "APPLY" if apply else "DRY-RUN"
        print(f"\nDone ({mode}). checked={checked}, missing={missing}")

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(repair(apply="--apply" in sys.argv))
