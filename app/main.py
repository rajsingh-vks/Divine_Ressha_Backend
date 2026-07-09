from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import connect_to_mongo
from app.routes import auth, health, permissions, roles, users


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

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)


@app.get("/", tags=["Root"])
async def read_root():
    return {
        "name": settings.app_name,
        "version": settings.api_version,
        "docs_url": "/docs",
        "roles": ["customer", "vendor", "admin"],
    }
