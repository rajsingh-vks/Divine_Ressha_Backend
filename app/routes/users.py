from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.dependencies import require_role
from app.schemas.auth import UserProfile
from app.schemas.users import AdminCreateRequest, UserAdminUpdate, UserOut, UserStatusUpdate
from app.security import hash_password


router = APIRouter(prefix="/users", tags=["User Management"])


def serialize_user(document: dict) -> UserOut:
    return UserOut(
        id=str(document["_id"]),
        email=document["email"],
        full_name=document.get("full_name"),
        phone=document.get("phone"),
        avatar_url=document.get("avatar_url"),
        bio=document.get("bio"),
        store_name=document.get("store_name"),
        role=document["role"],
        status=document["status"],
        email_verified=document.get("email_verified", False),
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


def _to_object_id(user_id: str) -> ObjectId:
    try:
        return ObjectId(user_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc


@router.get("", response_model=list[UserOut])
async def list_users(
    request: Request,
    current_admin=Depends(require_role("admin")),
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    role: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
):
    query: dict = {}
    if role:
        query["role"] = role
    if status_filter:
        query["status"] = status_filter

    cursor = request.app.state.mongo_db.users.find(query).sort("created_at", -1).skip(skip).limit(limit)
    documents = await cursor.to_list(length=limit)
    return [serialize_user(document) for document in documents]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    request: Request,
    user_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    document = await request.app.state.mongo_db.users.find_one({"_id": _to_object_id(user_id)})
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return serialize_user(document)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    payload: UserAdminUpdate,
    request: Request,
    user_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    update_data = {"updated_at": datetime.now(UTC)}

    for field in ("full_name", "phone", "avatar_url", "bio", "store_name", "role", "status", "email_verified"):
        value = getattr(payload, field)
        if value is not None:
            update_data[field] = value.strip() if isinstance(value, str) else value

    result = await request.app.state.mongo_db.users.update_one(
        {"_id": _to_object_id(user_id)},
        {"$set": update_data},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    document = await request.app.state.mongo_db.users.find_one({"_id": _to_object_id(user_id)})
    return serialize_user(document)


@router.patch("/{user_id}/status", response_model=UserOut)
async def update_user_status(
    payload: UserStatusUpdate,
    request: Request,
    user_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    result = await request.app.state.mongo_db.users.update_one(
        {"_id": _to_object_id(user_id)},
        {"$set": {"status": payload.status, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    document = await request.app.state.mongo_db.users.find_one({"_id": _to_object_id(user_id)})
    return serialize_user(document)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    request: Request,
    user_id: str = Path(...),
    hard: bool = Query(default=False),
    current_admin=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    user_obj_id = _to_object_id(user_id)

    if hard:
        if user_obj_id == current_admin["_id"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot hard delete your own account.")

        result = await db.users.delete_one({"_id": user_obj_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        await db.sessions.delete_many({"user_id": user_obj_id})
        return

    result = await db.users.update_one(
        {"_id": user_obj_id},
        {"$set": {"status": "deleted", "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


@router.post("/admin", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    payload: AdminCreateRequest,
    request: Request,
    current_admin=Depends(require_role("admin")),
):
    db = request.app.state.mongo_db
    email = payload.email.strip().lower()

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    now = datetime.now(UTC)
    salt, pw_hash = hash_password(payload.password)
    document = {
        "email": email,
        "password_salt": salt,
        "password_hash": pw_hash,
        "full_name": payload.full_name.strip() if payload.full_name else None,
        "phone": payload.phone.strip() if payload.phone else None,
        "avatar_url": None,
        "bio": payload.bio.strip() if payload.bio else None,
        "store_name": None,
        "role": "admin",
        "status": "active",
        "email_verified": True,
        "created_at": now,
        "updated_at": now,
        "created_by_admin_id": current_admin["_id"],
    }
    result = await db.users.insert_one(document)
    created = await db.users.find_one({"_id": result.inserted_id})
    return serialize_user(created)
