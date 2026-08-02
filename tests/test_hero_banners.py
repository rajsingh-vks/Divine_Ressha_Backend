from datetime import UTC, datetime

import pytest
import pytest_asyncio

import app.routes.hero_banners as hero_banners_route


@pytest_asyncio.fixture(autouse=True)
async def _clean_hero_banners_state(test_db):
    await test_db.hero_banners.delete_many({})


@pytest.fixture(autouse=True)
def _mock_banner_storage(monkeypatch):
    def _fake_save_banner_image(*, banner_id: str, filename: str, image_bytes: bytes, content_type: str | None):
        return f"/media/hero_banners/{banner_id}/{filename}"

    def _fake_delete_banner_media(_banner_id: str):
        return None

    monkeypatch.setattr(hero_banners_route.storage, "save_banner_image", _fake_save_banner_image)
    monkeypatch.setattr(hero_banners_route.storage, "delete_banner_media", _fake_delete_banner_media)


@pytest.mark.asyncio
async def test_create_hero_banner_without_auth(client):
    response = await client.post(
        "/api/admin/hero-banners",
        data={
            "title": "Monsoon Offer",
            "subtitle": "Fresh fragrances now live",
            "display_order": "1",
            "is_active": "true",
        },
        files={"image": ("hero.jpg", b"hero-bytes", "image/jpeg")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Monsoon Offer"
    assert payload["subtitle"] == "Fresh fragrances now live"
    assert payload["image_url"]


@pytest.mark.asyncio
async def test_create_hero_banner_without_auth_from_public_prefix(client):
    response = await client.post(
        "/hero-banners",
        data={
            "title": "Public Prefix",
            "subtitle": "No auth required",
        },
        files={"image": ("hero.jpg", b"hero-bytes", "image/jpeg")},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_list_hero_banners_homepage_only_active(client, test_db):
    now = datetime.now(UTC)
    await test_db.hero_banners.insert_many(
        [
            {
                "title": "Show Banner",
                "subtitle": "Visible",
                "image_url": "/media/hero_banners/a/one.jpg",
                "is_active": True,
                "display_order": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "Hide Banner",
                "subtitle": "Hidden",
                "image_url": "/media/hero_banners/b/two.jpg",
                "is_active": False,
                "display_order": 2,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    response = await client.get("/hero-banners")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "Show Banner"


@pytest.mark.asyncio
async def test_list_hero_banners_s3_url_is_proxied(client, test_db, monkeypatch):
    monkeypatch.setattr(hero_banners_route.settings, "aws_s3_bucket", "divine-reesha-assets")

    now = datetime.now(UTC)
    await test_db.hero_banners.insert_one(
        {
            "title": "S3 Banner",
            "subtitle": "Uses proxy",
            "image_url": "https://divine-reesha-assets.s3.ap-south-1.amazonaws.com/hero_banners/x/y.jpg",
            "is_active": True,
            "display_order": 1,
            "created_at": now,
            "updated_at": now,
        }
    )

    response = await client.get("/hero-banners")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert "/api/media?url=" in payload[0]["image_url"]


@pytest.mark.asyncio
async def test_update_hero_banner_without_auth(client):
    create_response = await client.post(
        "/api/admin/hero-banners",
        data={
            "title": "Original",
            "subtitle": "Original subtitle",
        },
        files={"image": ("hero.jpg", b"hero-bytes", "image/jpeg")},
    )
    assert create_response.status_code == 201
    banner_id = create_response.json()["id"]

    update_response = await client.put(
        f"/api/admin/hero-banners/{banner_id}",
        data={
            "title": "Updated",
            "subtitle": "Updated subtitle",
            "display_order": "5",
            "is_active": "false",
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["title"] == "Updated"
    assert payload["subtitle"] == "Updated subtitle"
    assert payload["display_order"] == 5
    assert payload["is_active"] is False


@pytest.mark.asyncio
async def test_delete_hero_banner_without_auth(client):
    create_response = await client.post(
        "/api/admin/hero-banners",
        data={"title": "Delete", "subtitle": "To remove"},
        files={"image": ("hero.jpg", b"hero-bytes", "image/jpeg")},
    )
    assert create_response.status_code == 201
    banner_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/admin/hero-banners/{banner_id}",
    )
    assert delete_response.status_code == 204
