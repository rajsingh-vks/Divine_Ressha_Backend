from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request, status

from app.security import hash_token


def _utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC (MongoDB returns naive UTC)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme.",
        )

    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing.",
        )
    return token


async def get_current_session(
    request: Request,
    authorization: str | None = Header(default=None),
):
    token = _extract_bearer_token(authorization)
    session = await request.app.state.mongo_db.sessions.find_one(
        {
            "access_token_hash": hash_token(token),
            "revoked_at": None,
        }
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )

    if _utc(session["access_expires_at"]) < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired.",
        )

    return session


async def get_current_user(request: Request, session=Depends(get_current_session)):
    user = await request.app.state.mongo_db.users.find_one({"_id": session["user_id"]})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    request.state.current_user = user
    request.state.current_session = session
    return user


def require_role(*allowed_roles: str) -> Callable:
    async def dependency(current_user=Depends(get_current_user)):
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return current_user

    return dependency
