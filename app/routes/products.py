from datetime import UTC, datetime
from pathlib import Path
import shutil
from urllib.parse import urlparse
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.config import get_settings
from app.dependencies import require_role
from app.schemas.products import ProductOut


router = APIRouter(prefix="/products", tags=["Products"])
settings = get_settings()

ALLOWED_STATUSES = {"Active", "Draft", "Archived"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid id format.",
        ) from exc


def _products_media_dir() -> Path:
    media_dir = Path(__file__).resolve().parents[2] / "media" / "products"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


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


def _extract_relative_media_path(raw_path: str) -> str | None:
    for prefix in ("/media/", "/api/media/"):
        if raw_path.startswith(prefix):
            return raw_path.removeprefix(prefix)
    return None


def _media_file_exists(relative_path: str) -> bool:
    return (_products_media_dir().parent / relative_path).exists()


def _normalize_image_url(request: Request, raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    base_url = _public_base_url(request)

    if raw_url.startswith("/media/"):
        rel_path = raw_url.removeprefix('/media/')
        if not _media_file_exists(rel_path):
            return None
        return f"{base_url}{_media_public_path(rel_path)}"

    if raw_url.startswith("/api/media/"):
        rel_path = raw_url.removeprefix('/api/media/')
        if not _media_file_exists(rel_path):
            return None
        return f"{base_url}{raw_url}"

    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        parsed = urlparse(raw_url)
        if parsed.path.startswith("/media/"):
            rel_path = parsed.path.removeprefix('/media/')
            if not _media_file_exists(rel_path):
                return None
            return f"{base_url}{_media_public_path(rel_path)}"
        if parsed.path.startswith("/api/media/"):
            rel_path = parsed.path.removeprefix('/api/media/')
            if not _media_file_exists(rel_path):
                return None
            return f"{base_url}{parsed.path}"

        rel_path = _extract_relative_media_path(parsed.path)
        if rel_path and not _media_file_exists(rel_path):
            return None

    return raw_url


def _serialize_product(document: dict, request: Request) -> ProductOut:
    return ProductOut(
        id=str(document["_id"]),
        name=document["name"],
        category=document["category"],
        subcategory=document.get("subcategory"),
        brand=document.get("brand"),
        fragrance=document.get("fragrance"),
        pack_size=document.get("pack_size"),
        form=document.get("form"),
        usage=document.get("usage"),
        price=float(document.get("price") or 0),
        stock=int(document.get("stock") or 0),
        sku=document.get("sku"),
        status=document.get("status", "Active"),
        image_url=_normalize_image_url(request, document.get("image_url")),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def _save_uploaded_image(product_id: ObjectId, image: UploadFile) -> str:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are allowed.")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image exceeds 5 MB limit.")

    extension = Path(image.filename).suffix.lower() or ".jpg"
    filename = f"{uuid4().hex}{extension}"
    product_dir = _products_media_dir() / str(product_id)
    product_dir.mkdir(parents=True, exist_ok=True)
    file_path = product_dir / filename
    file_path.write_bytes(image_bytes)

    relative_path = f"products/{product_id}/{filename}"
    return f"/media/{relative_path}"


def _remove_product_media_dir(product_id: ObjectId) -> None:
    product_dir = _products_media_dir() / str(product_id)
    if product_dir.exists():
        shutil.rmtree(product_dir)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    subcategory: str | None = Form(default=None),
    brand: str | None = Form(default=None),
    fragrance: str | None = Form(default=None),
    pack_size: str | None = Form(default=None),
    form: str | None = Form(default=None),
    usage: str | None = Form(default=None),
    price: float = Form(default=0),
    stock: int = Form(default=0),
    sku: str | None = Form(default=None),
    product_status: str = Form(default="Active", alias="status"),
    image: UploadFile | None = File(default=None),
    _admin_user=Depends(require_role("admin")),
):
    name = (name or "").strip()
    category = (category or "").strip()
    product_status = (product_status or "Active").strip().title()

    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name is required.")
    if not category:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Category is required.")
    if price < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Price cannot be negative.")
    if stock < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Stock cannot be negative.")
    if product_status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be one of: Active, Draft, Archived.",
        )

    db = request.app.state.mongo_db
    now = datetime.now(UTC)
    product_id = ObjectId()
    image_url: str | None = None

    if image and image.filename:
        image_url = await _save_uploaded_image(product_id, image)

    document = {
        "_id": product_id,
        "name": name,
        "category": category,
        "subcategory": _normalize_text(subcategory),
        "brand": _normalize_text(brand),
        "fragrance": _normalize_text(fragrance),
        "pack_size": _normalize_text(pack_size),
        "form": _normalize_text(form),
        "usage": _normalize_text(usage),
        "price": round(float(price), 2),
        "stock": int(stock),
        "sku": _normalize_text(sku),
        "status": product_status,
        "image_url": image_url,
        "created_at": now,
        "updated_at": now,
    }

    await db.products.insert_one(document)
    return _serialize_product(document, request)


@router.get("", response_model=list[ProductOut])
async def list_products(
    request: Request,
    limit: int = Query(default=24, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default="Active", alias="status"),
):
    query: dict = {}
    if status_filter:
        query["status"] = status_filter.strip().title()

    cursor = (
        request.app.state.mongo_db.products.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)
    return [_serialize_product(item, request) for item in items]


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(request: Request, product_id: str):
    product = await request.app.state.mongo_db.products.find_one({"_id": _to_object_id(product_id)})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return _serialize_product(product, request)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    request: Request,
    product_id: str,
    name: str | None = Form(default=None),
    category: str | None = Form(default=None),
    subcategory: str | None = Form(default=None),
    brand: str | None = Form(default=None),
    fragrance: str | None = Form(default=None),
    pack_size: str | None = Form(default=None),
    form: str | None = Form(default=None),
    usage: str | None = Form(default=None),
    price: float | None = Form(default=None),
    stock: int | None = Form(default=None),
    sku: str | None = Form(default=None),
    product_status: str | None = Form(default=None, alias="status"),
    image: UploadFile | None = File(default=None),
    _admin_user=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    product_obj_id = _to_object_id(product_id)
    existing = await db.products.find_one({"_id": product_obj_id})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    updates: dict = {}

    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name is required.")
        updates["name"] = cleaned

    if category is not None:
        cleaned = category.strip()
        if not cleaned:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Category is required.")
        updates["category"] = cleaned

    if subcategory is not None:
        updates["subcategory"] = _normalize_text(subcategory)
    if brand is not None:
        updates["brand"] = _normalize_text(brand)
    if fragrance is not None:
        updates["fragrance"] = _normalize_text(fragrance)
    if pack_size is not None:
        updates["pack_size"] = _normalize_text(pack_size)
    if form is not None:
        updates["form"] = _normalize_text(form)
    if usage is not None:
        updates["usage"] = _normalize_text(usage)
    if sku is not None:
        updates["sku"] = _normalize_text(sku)

    if price is not None:
        if price < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Price cannot be negative.")
        updates["price"] = round(float(price), 2)

    if stock is not None:
        if stock < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Stock cannot be negative.")
        updates["stock"] = int(stock)

    if product_status is not None:
        normalized_status = product_status.strip().title()
        if normalized_status not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Status must be one of: Active, Draft, Archived.",
            )
        updates["status"] = normalized_status

    if image and image.filename:
        _remove_product_media_dir(product_obj_id)
        updates["image_url"] = await _save_uploaded_image(product_obj_id, image)

    updates["updated_at"] = datetime.now(UTC)
    await db.products.update_one({"_id": product_obj_id}, {"$set": updates})
    updated = await db.products.find_one({"_id": product_obj_id})
    return _serialize_product(updated, request)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    request: Request,
    product_id: str,
    _admin_user=Depends(require_role("admin")),
):
    product_obj_id = _to_object_id(product_id)
    result = await request.app.state.mongo_db.products.delete_one({"_id": product_obj_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    _remove_product_media_dir(product_obj_id)
