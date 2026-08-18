from datetime import datetime

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    product_id: str = Field(..., min_length=12, max_length=50)
    order_id: str = Field(..., min_length=12, max_length=50)
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    id: str
    product_id: str
    order_id: str
    user_id: str
    rating: int
    comment: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
