from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.access_control import DEFAULT_ROLE_TEMPLATES, PERMISSION_CATALOG, current_utc
from app.dependencies import require_role
from app.schemas.access_control import RoleCreateRequest, RoleOut, RolePermissionsRequest, RoleUpdateRequest


router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


def serialize_role(document: dict) -> RoleOut:
    return RoleOut(
        id=str(document["_id"]),
        name=document["name"],
        description=document.get("description"),
        permissions=document.get("permissions", []),
        is_system=document.get("is_system", False),
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


def _to_object_id(role_id: str) -> ObjectId:
    try:
        return ObjectId(role_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role id.") from exc


def _validate_permissions(permissions: list[str]) -> None:
    allowed = {permission["code"] for permission in PERMISSION_CATALOG}
    invalid = sorted(set(permissions) - allowed)
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Unknown permissions supplied.", "invalid_permissions": invalid},
        )


@router.get("", response_model=list[RoleOut])
async def list_roles(request: Request, current_admin=Depends(require_role("admin"))):
    cursor = request.app.state.mongo_db.roles.find({}).sort("created_at", -1)
    documents = await cursor.to_list(length=100)

    if not documents:
        return [
            RoleOut(
                id=template["name"],
                name=template["name"],
                description=template["description"],
                permissions=template["permissions"],
                is_system=template["is_system"],
                created_at=current_utc(),
                updated_at=None,
            )
            for template in DEFAULT_ROLE_TEMPLATES
        ]

    return [serialize_role(document) for document in documents]


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreateRequest, request: Request, current_admin=Depends(require_role("admin"))):
    _validate_permissions(payload.permissions)
    now = datetime.now(UTC)
    document = {
        "name": payload.name.strip().lower(),
        "description": payload.description.strip() if payload.description else None,
        "permissions": payload.permissions,
        "is_system": False,
        "created_at": now,
        "updated_at": now,
    }
    result = await request.app.state.mongo_db.roles.insert_one(document)
    created = await request.app.state.mongo_db.roles.find_one({"_id": result.inserted_id})
    return serialize_role(created)


@router.put("/{role_id}", response_model=RoleOut)
async def update_role(
    payload: RoleUpdateRequest,
    request: Request,
    role_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    existing = await request.app.state.mongo_db.roles.find_one({"_id": _to_object_id(role_id)})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    if existing.get("is_system"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System roles cannot be edited directly.")

    update_data = {"updated_at": datetime.now(UTC)}
    if payload.name is not None:
        update_data["name"] = payload.name.strip().lower()
    if payload.description is not None:
        update_data["description"] = payload.description.strip()
    if payload.permissions is not None:
        _validate_permissions(payload.permissions)
        update_data["permissions"] = payload.permissions

    await request.app.state.mongo_db.roles.update_one({"_id": _to_object_id(role_id)}, {"$set": update_data})
    updated = await request.app.state.mongo_db.roles.find_one({"_id": _to_object_id(role_id)})
    return serialize_role(updated)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(request: Request, role_id: str = Path(...), current_admin=Depends(require_role("admin"))):
    existing = await request.app.state.mongo_db.roles.find_one({"_id": _to_object_id(role_id)})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    if existing.get("is_system"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System roles cannot be deleted.")

    await request.app.state.mongo_db.roles.delete_one({"_id": _to_object_id(role_id)})


@router.put("/{role_id}/permissions", response_model=RoleOut)
async def update_role_permissions(
    payload: RolePermissionsRequest,
    request: Request,
    role_id: str = Path(...),
    current_admin=Depends(require_role("admin")),
):
    _validate_permissions(payload.permissions)
    result = await request.app.state.mongo_db.roles.update_one(
        {"_id": _to_object_id(role_id)},
        {"$set": {"permissions": payload.permissions, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

    updated = await request.app.state.mongo_db.roles.find_one({"_id": _to_object_id(role_id)})
    return serialize_role(updated)
