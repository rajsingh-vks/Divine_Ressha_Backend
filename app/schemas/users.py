from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AccountRole = Literal["customer", "vendor", "admin"]
AccountStatus = Literal["pending", "active", "inactive", "suspended", "deleted"]


class UserOut(BaseModel):
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


class UserAdminUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=500)
    store_name: str | None = Field(default=None, max_length=120)
    role: AccountRole | None = None
    status: AccountStatus | None = None
    email_verified: bool | None = None


class UserStatusUpdate(BaseModel):
    status: AccountStatus = Field(...)
