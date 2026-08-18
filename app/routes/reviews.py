from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user
from app.schemas.reviews import ReviewCreate, ReviewOut, ReviewUpdate

router = APIRouter(tags=["Reviews"])


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id format.") from exc


def _serialize_review(document: dict) -> ReviewOut:
    return ReviewOut(
        id=str(document["_id"]),
        product_id=str(document["product_id"]),
        order_id=str(document["order_id"]),
        user_id=str(document["user_id"]),
        rating=int(document["rating"]),
        comment=document.get("comment"),
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


async def _get_purchased_product_for_order(db, user_id: ObjectId, product_id: ObjectId, order_id: ObjectId) -> dict:
    order = await db.orders.find_one({"_id": order_id, "user_id": user_id})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found for this user.")

    if order.get("status") != "delivered":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reviews can only be submitted after the order is delivered.")

    for item in order.get("items", []):
        if str(item.get("product_id")) == str(product_id):
            return order

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You have not purchased this product.")


@router.post("/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(payload: ReviewCreate, request: Request, current_user=Depends(get_current_user)):
    db = request.app.state.mongo_db
    user_id = current_user["_id"]
    product_obj_id = _to_object_id(payload.product_id)
    order_obj_id = _to_object_id(payload.order_id)

    product = await db.products.find_one({"_id": product_obj_id})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    await _get_purchased_product_for_order(db, user_id, product_obj_id, order_obj_id)

    existing = await db.reviews.find_one({
        "user_id": user_id,
        "product_id": product_obj_id,
        "order_id": order_obj_id,
    })
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already reviewed this product for this order.")

    now = datetime.now(UTC)
    document = {
        "user_id": user_id,
        "product_id": product_obj_id,
        "order_id": order_obj_id,
        "rating": int(payload.rating),
        "comment": payload.comment.strip() if payload.comment else None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.reviews.insert_one(document)
    inserted = await db.reviews.find_one({"_id": result.inserted_id})
    return _serialize_review(inserted)


@router.get("/products/{product_id}/reviews", response_model=list[ReviewOut])
async def list_product_reviews(request: Request, product_id: str):
    product_obj_id = _to_object_id(product_id)
    product = await request.app.state.mongo_db.products.find_one({"_id": product_obj_id})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    cursor = (
        request.app.state.mongo_db.reviews
        .find({"product_id": product_obj_id})
        .sort("created_at", -1)
    )
    documents = await cursor.to_list(length=200)
    return [_serialize_review(document) for document in documents]


@router.get("/reviews/me", response_model=list[ReviewOut])
async def get_my_reviews(request: Request, current_user=Depends(get_current_user)):
    cursor = (
        request.app.state.mongo_db.reviews
        .find({"user_id": current_user["_id"]})
        .sort("created_at", -1)
    )
    documents = await cursor.to_list(length=200)
    return [_serialize_review(document) for document in documents]


@router.put("/reviews/{review_id}", response_model=ReviewOut)
async def update_review(
    review_id: str,
    payload: ReviewUpdate,
    request: Request,
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    review_obj_id = _to_object_id(review_id)
    review = await db.reviews.find_one({"_id": review_obj_id, "user_id": current_user["_id"]})
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")

    updates: dict = {"updated_at": datetime.now(UTC)}
    if payload.rating is not None:
        updates["rating"] = int(payload.rating)
    if payload.comment is not None:
        updates["comment"] = payload.comment.strip() or None

    await db.reviews.update_one({"_id": review_obj_id}, {"$set": updates})
    updated = await db.reviews.find_one({"_id": review_obj_id})
    return _serialize_review(updated)


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(review_id: str, request: Request, current_user=Depends(get_current_user)):
    result = await request.app.state.mongo_db.reviews.delete_one({
        "_id": _to_object_id(review_id),
        "user_id": current_user["_id"],
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
