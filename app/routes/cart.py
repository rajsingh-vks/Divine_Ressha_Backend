from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.dependencies import get_current_user
from app.schemas.commerce import CartItemCreate, CartItemOut, CartItemUpdate, CartOut, ProductSummary


router = APIRouter(prefix="/cart", tags=["Cart"])


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


def _to_cart_item(document: dict, product: dict | None) -> CartItemOut:
    product_summary = (
        _serialize_product(product)
        if product
        else ProductSummary(id=str(document["product_id"]), name="Unavailable Product")
    )
    unit_price = product.get("price") if product else None
    line_total = (unit_price * document["quantity"]) if isinstance(unit_price, (int, float)) else None

    return CartItemOut(
        id=str(document["_id"]),
        product=product_summary,
        quantity=document["quantity"],
        unit_price=unit_price,
        line_total=line_total,
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


async def _build_cart_response(db, user_id) -> CartOut:
    cursor = db.cart.find({"user_id": user_id}).sort("created_at", -1)
    documents = await cursor.to_list(length=500)

    items: list[CartItemOut] = []
    subtotal = 0.0
    total_items = 0

    for document in documents:
        product = await db.products.find_one({"_id": document["product_id"]})
        item = _to_cart_item(document, product)
        items.append(item)
        total_items += item.quantity
        if item.line_total is not None:
            subtotal += item.line_total

    return CartOut(items=items, total_items=total_items, subtotal=round(subtotal, 2))


@router.get("", response_model=CartOut)
async def get_cart(request: Request, current_user=Depends(get_current_user)):
    return await _build_cart_response(request.app.state.mongo_db, current_user["_id"])


@router.post("", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    payload: CartItemCreate,
    request: Request,
    current_user=Depends(get_current_user),
):
    db = request.app.state.mongo_db
    user_id = current_user["_id"]
    product_obj_id = _to_object_id(payload.product_id)

    product = await db.products.find_one({"_id": product_obj_id})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    now = datetime.now(UTC)
    existing = await db.cart.find_one({"user_id": user_id, "product_id": product_obj_id})
    if existing:
        await db.cart.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "quantity": existing["quantity"] + payload.quantity,
                    "updated_at": now,
                }
            },
        )
    else:
        await db.cart.insert_one(
            {
                "user_id": user_id,
                "product_id": product_obj_id,
                "quantity": payload.quantity,
                "created_at": now,
                "updated_at": now,
            }
        )

    return await _build_cart_response(db, user_id)


@router.put("/{item_id}", response_model=CartOut)
async def update_cart_item(
    payload: CartItemUpdate,
    request: Request,
    item_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    obj_id = _to_object_id(item_id)
    result = await request.app.state.mongo_db.cart.update_one(
        {"_id": obj_id, "user_id": current_user["_id"]},
        {"$set": {"quantity": payload.quantity, "updated_at": datetime.now(UTC)}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found.")

    return await _build_cart_response(request.app.state.mongo_db, current_user["_id"])


@router.delete("/{item_id}", response_model=CartOut)
async def delete_cart_item(
    request: Request,
    item_id: str = Path(...),
    current_user=Depends(get_current_user),
):
    obj_id = _to_object_id(item_id)
    result = await request.app.state.mongo_db.cart.delete_one(
        {"_id": obj_id, "user_id": current_user["_id"]}
    )

    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found.")

    return await _build_cart_response(request.app.state.mongo_db, current_user["_id"])


@router.delete("", response_model=CartOut)
async def clear_cart(request: Request, current_user=Depends(get_current_user)):
    await request.app.state.mongo_db.cart.delete_many({"user_id": current_user["_id"]})
    return CartOut(items=[], total_items=0, subtotal=0.0)
