from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AccountRole = Literal["customer", "vendor", "admin"]
AccountStatus = Literal["pending", "active", "inactive", "suspended", "deleted"]


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 86400


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    store_name: str | None = None
    role: AccountRole
    status: AccountStatus
    email_verified: bool
    created_at: datetime
    updated_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    role: Literal["customer", "vendor"] = "customer"
    store_name: str | None = Field(default=None, max_length=120)


class SignupInitiateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    phone: str = Field(..., min_length=6, max_length=30)
    role: Literal["customer", "vendor"] = "customer"
    store_name: str | None = Field(default=None, max_length=120)


class SignupInitiateResponse(BaseModel):
    message: str
    email: str
    phone: str
    expires_in_seconds: int
    email_verification_code: str | None = None
    mobile_verification_code: str | None = None


class SignupCompleteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    email_code: str = Field(..., min_length=4, max_length=10)
    mobile_code: str = Field(..., min_length=4, max_length=10)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class LogoutResponse(BaseModel):
    message: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20)
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=20)


class ResendVerificationRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=500)
    store_name: str | None = Field(default=None, max_length=120)


class AuthResponse(BaseModel):
    message: str
    user: UserProfile
    tokens: AuthTokens | None = None
