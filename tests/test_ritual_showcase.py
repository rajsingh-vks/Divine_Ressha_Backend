from datetime import UTC, datetime

import pytest
import pytest_asyncio

import app.routes.ritual_showcase as ritual_showcase_route


@pytest_asyncio.fixture(autouse=True)
async def _clean_ritual_showcase_state(test_db):
    await test_db.ritual_showcase.delete_many({})


@pytest.fixture(autouse=True)
def _mock_ritual_storage(monkeypatch):
    def _fake_save(*, item_id: str, filename: str, image_bytes: bytes, content_type: str | None):
        return f"/media/ritual_showcase/{item_id}/{filename}"

    def _fake_delete(_item_id: str):
        return None

    monkeypatch.setattr(ritual_showcase_route.storage, "save_ritual_showcase_image", _fake_save)
    monkeypatch.setattr(ritual_showcase_route.storage, "delete_ritual_showcase_media", _fake_delete)


@pytest.mark.asyncio
async def test_create_ritual_showcase_item(client):
    response = await client.post(
        "/api/admin/ritual-showcase",
        data={
            "title": "The Bath Collection",
            "subtitle": "Clean Ritual",
            "description": "Body wash and hand-cut soaps.",
            "display_order": "1",
            "is_active": "true",
        },
        files={"image": ("ritual.jpg", b"ritual-bytes", "image/jpeg")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "The Bath Collection"
    assert payload["subtitle"] == "Clean Ritual"
    assert payload["image_url"]


@pytest.mark.asyncio
async def test_list_ritual_showcase_only_active(client, test_db):
    now = datetime.now(UTC)
    await test_db.ritual_showcase.insert_many(
        [
            {
                "title": "Visible",
                "subtitle": "Show",
                "description": "Visible card",
                "image_url": "/media/ritual_showcase/a/one.jpg",
                "is_active": True,
                "display_order": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "Hidden",
                "subtitle": "Hide",
                "description": "Hidden card",
                "image_url": "/media/ritual_showcase/b/two.jpg",
                "is_active": False,
                "display_order": 2,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    response = await client.get("/ritual-showcase")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "Visible"


@pytest.mark.asyncio
async def test_update_ritual_showcase_item(client):
    create_response = await client.post(
        "/api/admin/ritual-showcase",
        data={
            "title": "Old Title",
            "subtitle": "Old Subtitle",
        },
        files={"image": ("ritual.jpg", b"ritual-bytes", "image/jpeg")},
    )
    assert create_response.status_code == 201
    item_id = create_response.json()["id"]

    update_response = await client.put(
        f"/api/admin/ritual-showcase/{item_id}",
        data={
            "title": "New Title",
            "subtitle": "New Subtitle",
            "description": "New Desc",
            "display_order": "4",
            "is_active": "false",
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["title"] == "New Title"
    assert payload["subtitle"] == "New Subtitle"
    assert payload["description"] == "New Desc"
    assert payload["display_order"] == 4
    assert payload["is_active"] is False


@pytest.mark.asyncio
async def test_delete_ritual_showcase_item(client):
    create_response = await client.post(
        "/api/admin/ritual-showcase",
        data={"title": "Delete", "subtitle": "Remove"},
        files={"image": ("ritual.jpg", b"ritual-bytes", "image/jpeg")},
    )
    assert create_response.status_code == 201
    item_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/admin/ritual-showcase/{item_id}")
    assert delete_response.status_code == 204
