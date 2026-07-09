from datetime import datetime

from pydantic import BaseModel, Field


class PermissionOut(BaseModel):
    code: str
    name: str
    group: str
    description: str


class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] | None = None


class RolePermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class RoleOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    permissions: list[str]
    is_system: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class PermissionCatalogResponse(BaseModel):
    permissions: list[PermissionOut]
    default_roles: list[dict]
