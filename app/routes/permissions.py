from fastapi import APIRouter

from app.access_control import DEFAULT_ROLE_TEMPLATES, PERMISSION_CATALOG
from app.schemas.access_control import PermissionCatalogResponse, PermissionOut


router = APIRouter(tags=["Roles & Permissions"])


@router.get("/permissions", response_model=PermissionCatalogResponse)
async def list_permissions():
    return PermissionCatalogResponse(
        permissions=[PermissionOut(**permission) for permission in PERMISSION_CATALOG],
        default_roles=DEFAULT_ROLE_TEMPLATES,
    )
