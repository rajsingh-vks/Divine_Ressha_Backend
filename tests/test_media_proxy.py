from io import BytesIO

import pytest

import app.main as app_main


class _FakeS3Client:
    def get_object(self, Bucket: str, Key: str):
        assert Bucket
        assert Key
        return {
            "Body": BytesIO(b"image-bytes"),
            "ContentType": "image/jpeg",
        }


@pytest.mark.asyncio
async def test_api_media_proxies_configured_s3_url(client, monkeypatch):
    monkeypatch.setattr(app_main.settings, "aws_s3_bucket", "divine-reesha-assets")
    monkeypatch.setattr(app_main.settings, "aws_region", "ap-south-1")
    monkeypatch.setattr(app_main.boto3, "client", lambda *_args, **_kwargs: _FakeS3Client())

    response = await client.get(
        "/api/media",
        params={"url": "https://divine-reesha-assets.s3.ap-south-1.amazonaws.com/hero_banners/x/y.jpg"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("image/jpeg")
    assert response.content == b"image-bytes"


@pytest.mark.asyncio
async def test_api_media_redirects_to_external_http_url(client, monkeypatch):
    monkeypatch.setattr(app_main.settings, "aws_s3_bucket", "divine-reesha-assets")

    response = await client.get(
        "/api/media",
        params={"url": "https://example.com/assets/banner.jpg"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert response.headers.get("location", "").startswith("https://example.com/assets/banner.jpg")


@pytest.mark.asyncio
async def test_api_media_rejects_non_http_url(client):
    response = await client.get(
        "/api/media",
        params={"url": "file:///tmp/test.jpg"},
        follow_redirects=False,
    )

    assert response.status_code == 400
