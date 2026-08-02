from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import boto3
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import connect_to_mongo
from app.routes import (
    addresses,
    auth,
    aws_sns,
    cart,
    hero_banners,
    health,
    orders,
    payments,
    permissions,
    products,
    razorpay_checkout,
    ritual_showcase,
    roles,
    users,
    wishlist,
)


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_client = await connect_to_mongo(settings)
    app.state.mongo_client = mongo_client
    app.state.mongo_db = mongo_client[settings.mongodb_database]
    yield
    mongo_client.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
    description="Python backend API for Divine Reesha with MongoDB integration.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

media_dir = Path(__file__).resolve().parents[1] / "media"
media_dir.mkdir(parents=True, exist_ok=True)


def _is_configured_s3_media_url(parsed) -> bool:
    if not settings.aws_s3_bucket:
        return False
    hostname = (parsed.hostname or "").lower()
    bucket = settings.aws_s3_bucket.lower()
    return hostname.startswith(f"{bucket}.s3") and hostname.endswith("amazonaws.com")


def _s3_client():
    kwargs = {}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    return boto3.client("s3", **kwargs)


@app.get("/api/media", tags=["Media"])
async def resolve_media_url(url: str = Query(..., description="Absolute media URL to resolve")):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http/https media URLs are supported.")

    if _is_configured_s3_media_url(parsed):
        key = parsed.path.lstrip("/")
        if not key:
            raise HTTPException(status_code=400, detail="Invalid S3 media URL path.")

        try:
            obj = _s3_client().get_object(Bucket=settings.aws_s3_bucket, Key=key)
            body_bytes = obj["Body"].read()
            media_type = obj.get("ContentType") or "application/octet-stream"
            return StreamingResponse(BytesIO(body_bytes), media_type=media_type)
        except Exception:
            raise HTTPException(status_code=404, detail="Media file not found.")

    return RedirectResponse(url=url)


app.mount("/media", StaticFiles(directory=media_dir), name="media")
app.mount("/api/media", StaticFiles(directory=media_dir), name="api-media")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth.router, prefix="/api")
app.include_router(hero_banners.router)
app.include_router(hero_banners.router, prefix="/api")
app.include_router(hero_banners.router, prefix="/api/admin")
app.include_router(hero_banners.router, prefix="/admin")
app.include_router(ritual_showcase.router)
app.include_router(ritual_showcase.router, prefix="/api")
app.include_router(ritual_showcase.router, prefix="/api/admin")
app.include_router(ritual_showcase.router, prefix="/admin")
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(wishlist.router)
app.include_router(cart.router)
app.include_router(products.router)
app.include_router(addresses.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(razorpay_checkout.router)
app.include_router(aws_sns.router)


@app.get("/", tags=["Root"])
async def read_root():
    return {
        "name": settings.app_name,
        "version": settings.api_version,
        "docs_url": "/docs",
        "roles": ["customer", "vendor", "admin"],
    }
