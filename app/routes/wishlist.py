from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.dependencies import get_current_user
from app.schemas.commerce import ProductSummary, WishlistItemOut


router = APIRouter(prefix="/wishlist", tags=["Wishlist"])


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid id format.",
        ) from exc


def _serialize_product(document: dict) -> ProductSummary:
    return ProductSummary(
        id=str(document["_id"]),
        name=document.get("name", "Unknown Product"),
        brand=document.get("brand"),
        category=document.get("category"),
        subcategory=document.get("subcategory"),
        price=document.get("price"),
        image_url=document.get("image_url"),
    )


async def _enrich_wishlist_item(db, item: dict) -> WishlistItemOut:
    product = await db.products.find_one({"_id": item["product_id"]})
    if product:
        product_summary = _serialize_product(product)
    else:
        product_summary = ProductSummary(
            id=str(item["product_id"]),
            name="Unavailable Product",
        )

    return WishlistItemOut(
        id=str(item["_id"]),
        product=product_summary,
        created_at=item["created_at"],
    )


@router.get("", response_model=list[WishlistItemOut])
async def get_wishlist(request: Request, current_user=Depends(get_current_user)):
    user_id = current_user["_id"]
    cursor = (
        request.app.state.mongo_db.wishlist
        .find({"user_id": user_id})
        .sort("created_at", -1)
    )
    items = await cursor.to_list(length=500)

    enriched = []
    for item in items:
        enriched.append(await _enrich_wishlist_item(request.app.state.mongo_db, item))
    return enriched


@router.post("/{product_id}", response_model=WishlistItemOut, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    request: Request,
    product_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    user_id = current_user["_id"]
    product_obj_id = _to_object_id(product_id)

    product = await db.products.find_one({"_id": product_obj_id})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    existing = await db.wishlist.find_one({"user_id": user_id, "product_id": product_obj_id})
    if existing:
        return await _enrich_wishlist_item(db, existing)

    now = datetime.now(UTC)
    result = await db.wishlist.insert_one(
        {
            "user_id": user_id,
            "product_id": product_obj_id,
            "created_at": now,
        }
    )
    document = await db.wishlist.find_one({"_id": result.inserted_id})
    return await _enrich_wishlist_item(db, document)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    request: Request,
    product_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    product_obj_id = _to_object_id(product_id)
    result = await request.app.state.mongo_db.wishlist.delete_one(
        {
            "user_id": current_user["_id"],
            "product_id": product_obj_id,
        }
    )

    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wishlist item not found.")
