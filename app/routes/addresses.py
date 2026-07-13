from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.dependencies import get_current_user
from app.schemas.orders import AddressCreate, AddressOut, AddressUpdate


router = APIRouter(prefix="/addresses", tags=["Addresses"])


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id format.") from exc


def _serialize_address(document: dict) -> AddressOut:
    return AddressOut(
        id=str(document["_id"]),
        full_name=document["full_name"],
        phone=document["phone"],
        line1=document["line1"],
        line2=document.get("line2"),
        city=document["city"],
        state=document["state"],
        postal_code=document["postal_code"],
        country=document["country"],
        address_type=document.get("address_type", "home"),
        is_default=bool(document.get("is_default", False)),
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


@router.get("", response_model=list[AddressOut])
async def list_addresses(request: Request, current_user=Depends(get_current_user)):
    cursor = (
        request.app.state.mongo_db.addresses.find({"user_id": current_user["_id"]})
        .sort([("is_default", -1), ("created_at", -1)])
    )
    items = await cursor.to_list(length=200)
    return [_serialize_address(item) for item in items]


@router.post("", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(payload: AddressCreate, request: Request, current_user=Depends(get_current_user)):
    db = request.app.state.mongo_db
    user_id = current_user["_id"]
    now = datetime.now(UTC)

    existing_count = await db.addresses.count_documents({"user_id": user_id})
    is_default = payload.is_default or existing_count == 0

    if is_default:
        await db.addresses.update_many({"user_id": user_id}, {"$set": {"is_default": False}})

    document = {
        "user_id": user_id,
        "full_name": payload.full_name.strip(),
        "phone": payload.phone.strip(),
        "line1": payload.line1.strip(),
        "line2": payload.line2.strip() if payload.line2 else None,
        "city": payload.city.strip(),
        "state": payload.state.strip(),
        "postal_code": payload.postal_code.strip(),
        "country": payload.country.strip(),
        "address_type": payload.address_type.strip().lower(),
        "is_default": is_default,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.addresses.insert_one(document)
    created = await db.addresses.find_one({"_id": result.inserted_id})
    return _serialize_address(created)


@router.put("/{address_id}", response_model=AddressOut)
async def update_address(
    payload: AddressUpdate,
    request: Request,
    address_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    address_obj_id = _to_object_id(address_id)
    existing = await db.addresses.find_one({"_id": address_obj_id, "user_id": current_user["_id"]})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.")

    update_data: dict = {}
    for field in (
        "full_name",
        "phone",
        "line1",
        "line2",
        "city",
        "state",
        "postal_code",
        "country",
        "address_type",
        "is_default",
    ):
        value = getattr(payload, field)
        if value is not None:
            if isinstance(value, str):
                value = value.strip()
            if field == "address_type" and isinstance(value, str):
                value = value.lower()
            update_data[field] = value

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update.")

    if update_data.get("is_default") is True:
        await db.addresses.update_many(
            {"user_id": current_user["_id"], "_id": {"$ne": address_obj_id}},
            {"$set": {"is_default": False}},
        )

    update_data["updated_at"] = datetime.now(UTC)
    await db.addresses.update_one({"_id": address_obj_id}, {"$set": update_data})
    updated = await db.addresses.find_one({"_id": address_obj_id})
    return _serialize_address(updated)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    request: Request,
    address_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    address_obj_id = _to_object_id(address_id)
    existing = await db.addresses.find_one({"_id": address_obj_id, "user_id": current_user["_id"]})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.")

    await db.addresses.delete_one({"_id": address_obj_id, "user_id": current_user["_id"]})

    if existing.get("is_default"):
        next_address = await db.addresses.find_one(
            {"user_id": current_user["_id"]},
            sort=[("created_at", -1)],
        )
        if next_address:
            await db.addresses.update_one({"_id": next_address["_id"]}, {"$set": {"is_default": True}})


@router.patch("/{address_id}/default", response_model=AddressOut)
async def set_default_address(
    request: Request,
    address_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    address_obj_id = _to_object_id(address_id)
    existing = await db.addresses.find_one({"_id": address_obj_id, "user_id": current_user["_id"]})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.")

    await db.addresses.update_many({"user_id": current_user["_id"]}, {"$set": {"is_default": False}})
    await db.addresses.update_one(
        {"_id": address_obj_id},
        {"$set": {"is_default": True, "updated_at": datetime.now(UTC)}},
    )
    updated = await db.addresses.find_one({"_id": address_obj_id})
    return _serialize_address(updated)
