from datetime import datetime

from pydantic import BaseModel


class ProductOut(BaseModel):
    id: str
    name: str
    category: str
    subcategory: str | None = None
    brand: str | None = None
    fragrance: str | None = None
    pack_size: str | None = None
    form: str | None = None
    usage: str | None = None
    price: float = 0
    stock: int = 0
    sku: str | None = None
    status: str = "Active"
    image_url: str | None = None
    created_at: datetime
    updated_at: datetime
