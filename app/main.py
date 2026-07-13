from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import connect_to_mongo
from app.routes import auth, cart, health, permissions, products, roles, users, wishlist


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
app.mount("/media", StaticFiles(directory=media_dir), name="media")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(wishlist.router)
app.include_router(cart.router)
app.include_router(products.router)


@app.get("/", tags=["Root"])
async def read_root():
    return {
        "name": settings.app_name,
        "version": settings.api_version,
        "docs_url": "/docs",
        "roles": ["customer", "vendor", "admin"],
    }
