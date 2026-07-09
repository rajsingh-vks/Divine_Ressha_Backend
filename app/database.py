from typing import Annotated

from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings


async def connect_to_mongo(settings: Settings) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)


def get_database(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.mongo_db


Database = Annotated[AsyncIOMotorDatabase, Depends(get_database)]
