from datetime import datetime

from pydantic import BaseModel, Field


class ProductSummary(BaseModel):
    id: str
    name: str
    brand: str | None = None
    category: str | None = None
    subcategory: str | None = None
    price: float | None = None
    image_url: str | None = None


class WishlistItemOut(BaseModel):
    id: str
    product: ProductSummary
    created_at: datetime


class CartItemCreate(BaseModel):
    product_id: str = Field(..., min_length=24, max_length=24)
    quantity: int = Field(default=1, ge=1, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(..., ge=1, le=100)


class CartItemOut(BaseModel):
    id: str
    product: ProductSummary
    quantity: int
    unit_price: float | None = None
    line_total: float | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CartOut(BaseModel):
    items: list[CartItemOut]
    total_items: int
    subtotal: float
