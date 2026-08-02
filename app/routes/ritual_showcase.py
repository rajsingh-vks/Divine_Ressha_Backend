from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from app.config import get_settings
from app.schemas.ritual_showcase import RitualShowcaseOut
from app.services.storage import ProductImageStorage


router = APIRouter(prefix="/ritual-showcase", tags=["Ritual Showcase"])
settings = get_settings()
storage = ProductImageStorage(settings=settings, project_root=Path(__file__).resolve().parents[2])

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id format.") from exc


def _public_base_url(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _media_public_path(relative_path: str) -> str:
    return f"{settings.media_url_prefix}/{relative_path.lstrip('/')}"


def _normalize_image_url(request: Request, raw_url: str | None) -> str:
    if not raw_url:
        return ""

    base_url = _public_base_url(request)

    if raw_url.startswith("/media/"):
        rel_path = raw_url.removeprefix("/media/")
        return f"{base_url}{_media_public_path(rel_path)}"

    if raw_url.startswith("/api/media/"):
        return f"{base_url}{raw_url}"

    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        parsed = urlparse(raw_url)
        bucket = (settings.aws_s3_bucket or "").strip().lower()
        host = (parsed.netloc or "").lower()
        if bucket and host.startswith(f"{bucket}.s3") and host.endswith("amazonaws.com"):
            encoded = quote(raw_url, safe="")
            return f"{base_url}/api/media?url={encoded}"

        if parsed.path.startswith("/media/"):
            rel_path = parsed.path.removeprefix("/media/")
            return f"{base_url}{_media_public_path(rel_path)}"
        if parsed.path.startswith("/api/media/"):
            return f"{base_url}{parsed.path}"

    return raw_url


def _serialize_item(document: dict, request: Request) -> RitualShowcaseOut:
    return RitualShowcaseOut(
        id=str(document["_id"]),
        title=document["title"],
        subtitle=document["subtitle"],
        description=document.get("description"),
        image_url=_normalize_image_url(request, document.get("image_url")),
        is_active=bool(document.get("is_active", True)),
        display_order=int(document.get("display_order", 0)),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


async def _save_uploaded_image(item_id: ObjectId, image: UploadFile) -> str:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are allowed.")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image exceeds 8 MB limit.")

    extension = Path(image.filename or "").suffix.lower() or ".jpg"
    filename = f"{uuid4().hex}{extension}"
    return storage.save_ritual_showcase_image(
        item_id=str(item_id),
        filename=filename,
        image_bytes=image_bytes,
        content_type=image.content_type,
    )


@router.post("", response_model=RitualShowcaseOut, status_code=status.HTTP_201_CREATED)
async def create_ritual_showcase_item(
    request: Request,
    title: str = Form(...),
    subtitle: str = Form(...),
    description: str | None = Form(default=None),
    image: UploadFile = File(...),
    display_order: int = Form(default=0),
    is_active: bool = Form(default=True),
):
    clean_title = (title or "").strip()
    clean_subtitle = (subtitle or "").strip()
    clean_description = (description or "").strip() if description is not None else None

    if not clean_title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title is required.")
    if not clean_subtitle:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subtitle is required.")

    now = datetime.now(UTC)
    item_id = ObjectId()
    image_url = await _save_uploaded_image(item_id, image)

    document = {
        "_id": item_id,
        "title": clean_title,
        "subtitle": clean_subtitle,
        "description": clean_description,
        "image_url": image_url,
        "display_order": int(display_order),
        "is_active": bool(is_active),
        "created_at": now,
        "updated_at": now,
    }
    await request.app.state.mongo_db.ritual_showcase.insert_one(document)
    return _serialize_item(document, request)


@router.get("", response_model=list[RitualShowcaseOut])
async def list_ritual_showcase_items(
    request: Request,
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
):
    query: dict = {} if include_inactive else {"is_active": True}
    cursor = (
        request.app.state.mongo_db.ritual_showcase.find(query)
        .sort([("display_order", 1), ("created_at", -1)])
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)
    return [_serialize_item(item, request) for item in items]


@router.put("/{item_id}", response_model=RitualShowcaseOut)
async def update_ritual_showcase_item(
    request: Request,
    item_id: str,
    title: str | None = Form(default=None),
    subtitle: str | None = Form(default=None),
    description: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    display_order: int | None = Form(default=None),
    is_active: bool | None = Form(default=None),
):
    db = request.app.state.mongo_db
    obj_id = _to_object_id(item_id)
    existing = await db.ritual_showcase.find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ritual showcase item not found.")

    updates: dict = {}
    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title is required.")
        updates["title"] = clean_title

    if subtitle is not None:
        clean_subtitle = subtitle.strip()
        if not clean_subtitle:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subtitle is required.")
        updates["subtitle"] = clean_subtitle

    if description is not None:
        updates["description"] = description.strip() or None

    if display_order is not None:
        updates["display_order"] = int(display_order)
    if is_active is not None:
        updates["is_active"] = bool(is_active)

    if image and image.filename:
        storage.delete_ritual_showcase_media(str(obj_id))
        updates["image_url"] = await _save_uploaded_image(obj_id, image)

    if not updates:
        return _serialize_item(existing, request)

    updates["updated_at"] = datetime.now(UTC)
    await db.ritual_showcase.update_one({"_id": obj_id}, {"$set": updates})
    updated = await db.ritual_showcase.find_one({"_id": obj_id})
    return _serialize_item(updated, request)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ritual_showcase_item(request: Request, item_id: str):
    obj_id = _to_object_id(item_id)
    result = await request.app.state.mongo_db.ritual_showcase.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ritual showcase item not found.")
    storage.delete_ritual_showcase_media(str(obj_id))
