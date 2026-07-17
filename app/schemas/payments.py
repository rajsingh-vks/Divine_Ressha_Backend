from pydantic import BaseModel, Field


class RazorpayCreateOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=24, max_length=24)


class RazorpayOrderOut(BaseModel):
    key_id: str
    backend_order_id: str
    order_number: str
    razorpay_order_id: str
    amount: int
    currency: str


class RazorpayVerifyRequest(BaseModel):
    order_id: str = Field(..., min_length=24, max_length=24)
    razorpay_order_id: str = Field(..., min_length=5)
    razorpay_payment_id: str = Field(..., min_length=5)
    razorpay_signature: str = Field(..., min_length=10)


class RazorpayVerifyOut(BaseModel):
    success: bool
    message: str
    backend_order_id: str
    payment_status: str
    order_status: str


class CheckoutCreateOrderRequest(BaseModel):
    amount: int = Field(..., ge=1, description="Amount in paise")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    receipt: str | None = Field(default=None, max_length=100)


class CheckoutCreateOrderOut(BaseModel):
    order_id: str
    amount: int
    currency: str


class CheckoutVerifyPaymentRequest(BaseModel):
    razorpay_order_id: str | None = Field(default=None)
    razorpay_payment_id: str | None = Field(default=None)
    razorpay_signature: str | None = Field(default=None)


class CheckoutVerifyPaymentOut(BaseModel):
    success: bool
    message: str


class RazorpayRefundCreateRequest(BaseModel):
    order_id: str = Field(..., min_length=24, max_length=24)
    amount: int | None = Field(default=None, ge=1, description="Amount in paise. Defaults to full paid amount.")
    reason: str | None = Field(default=None, max_length=500)


class RazorpayRefundOut(BaseModel):
    success: bool
    message: str
    backend_order_id: str
    refund_id: str
    payment_id: str
    amount: int
    currency: str
    status: str


class RazorpayRefundStatusOut(BaseModel):
    refund_id: str
    payment_id: str
    amount: int
    currency: str
    status: str
    speed_processed: str | None = None
    created_at: int | None = None
