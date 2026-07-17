from datetime import datetime

from pydantic import BaseModel, Field


class AddressBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=3, max_length=30)
    line1: str = Field(..., min_length=2, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str = Field(..., min_length=1, max_length=120)
    state: str = Field(..., min_length=1, max_length=120)
    postal_code: str = Field(..., min_length=2, max_length=30)
    country: str = Field(..., min_length=2, max_length=120)
    address_type: str = Field(default="home", max_length=20)
    is_default: bool = False


class AddressCreate(AddressBase):
    pass


class AddressUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=3, max_length=30)
    line1: str | None = Field(default=None, min_length=2, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    state: str | None = Field(default=None, min_length=1, max_length=120)
    postal_code: str | None = Field(default=None, min_length=2, max_length=30)
    country: str | None = Field(default=None, min_length=2, max_length=120)
    address_type: str | None = Field(default=None, max_length=20)
    is_default: bool | None = None


class AddressOut(AddressBase):
    id: str
    created_at: datetime
    updated_at: datetime | None = None


class OrderItemOut(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    unit_price: float | None = None
    quantity: int
    line_total: float | None = None


class AddressSnapshot(BaseModel):
    full_name: str
    phone: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str
    address_type: str


class OrderCreate(BaseModel):
    address_id: str = Field(..., min_length=24, max_length=24)
    notes: str | None = Field(default=None, max_length=1000)


class OrderStatusUpdate(BaseModel):
    status: str = Field(..., min_length=3, max_length=30)


class OrderCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OrderStatusHistory(BaseModel):
    status: str
    note: str | None = None
    changed_at: datetime
    changed_by: str | None = None


class OrderOut(BaseModel):
    id: str
    order_number: str
    user_id: str
    status: str
    items: list[OrderItemOut]
    shipping_address: AddressSnapshot
    total_items: int
    subtotal: float
    notes: str | None = None
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    payment_status: str | None = None
    return_status: str | None = None
    return_reason: str | None = None
    return_requested_at: datetime | None = None
    refund_status: str | None = None
    refund_amount: float | None = None
    refund_reason: str | None = None
    refund_reference: str | None = None
    refund_requested_at: datetime | None = None
    refunded_at: datetime | None = None
    status_history: list[OrderStatusHistory] = []
    created_at: datetime
    updated_at: datetime


class OrderReturnRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class OrderRefundUpdateRequest(BaseModel):
    status: str = Field(..., min_length=3, max_length=20)
    reason: str | None = Field(default=None, max_length=500)
    refund_reference: str | None = Field(default=None, max_length=120)


class OrderRefundSummaryOut(BaseModel):
    order_id: str
    order_number: str
    user_id: str
    order_status: str
    payment_status: str | None = None
    return_status: str | None = None
    refund_status: str | None = None
    refund_amount: float | None = None
    refund_reason: str | None = None
    refund_reference: str | None = None
    refund_requested_at: datetime | None = None
    refunded_at: datetime | None = None
    updated_at: datetime
