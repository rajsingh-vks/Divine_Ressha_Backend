from datetime import UTC, datetime
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.auth import (
    AuthResponse,
    AuthTokens,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    SignupCompleteRequest,
    SignupInitiateRequest,
    SignupInitiateResponse,
    RefreshTokenRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    UserProfile,
    VerifyEmailRequest,
)
from app.security import (
    ACCESS_TOKEN_TTL,
    PASSWORD_RESET_TOKEN_TTL,
    ONE_TIME_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    generate_token_pair,
    hash_password,
    hash_token,
    verify_password,
)
from app.services.notifications import send_email_verification_code_detailed, send_sms_verification_code_detailed


router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


def _utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC (MongoDB returns naive UTC)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def serialize_user(document: dict) -> UserProfile:
    return UserProfile(
        id=str(document["_id"]),
        email=document["email"],
        full_name=document.get("full_name"),
        phone=document.get("phone"),
        avatar_url=document.get("avatar_url"),
        bio=document.get("bio"),
        store_name=document.get("store_name"),
        role=document["role"],
        status=document["status"],
        email_verified=document.get("email_verified", False),
        created_at=document["created_at"],
        updated_at=document.get("updated_at"),
    )


def _build_session(user_id, role: str) -> tuple[str, str, dict]:
    access_token, refresh_token = generate_token_pair()
    now = datetime.now(UTC)
    return (
        access_token,
        refresh_token,
        {
            "user_id": user_id,
            "role": role,
            "access_token_hash": hash_token(access_token),
            "refresh_token_hash": hash_token(refresh_token),
            "created_at": now,
            "access_expires_at": now + ACCESS_TOKEN_TTL,
            "refresh_expires_at": now + REFRESH_TOKEN_TTL,
            "revoked_at": None,
        },
    )


def _build_one_time_token() -> tuple[str, dict]:
    token = generate_token_pair()[0]
    now = datetime.now(UTC)
    return token, {
        "token_hash": hash_token(token),
        "created_at": now,
        "expires_at": now + ONE_TIME_TOKEN_TTL,
        "consumed_at": None,
    }


def _generate_verification_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


@router.post("/signup/initiate", response_model=SignupInitiateResponse)
async def initiate_signup(payload: SignupInitiateRequest, request: Request):
    db = request.app.state.mongo_db
    email = payload.email.strip().lower()

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    now = datetime.now(UTC)
    email_code = _generate_verification_code()
    mobile_code = _generate_verification_code()
    password_salt, password_hash = hash_password(payload.password)

    await db.signup_verifications.update_one(
        {"email": email},
        {
            "$set": {
                "email": email,
                "password_salt": password_salt,
                "password_hash": password_hash,
                "full_name": payload.full_name.strip() if payload.full_name else None,
                "phone": payload.phone.strip(),
                "role": payload.role,
                "store_name": payload.store_name.strip() if payload.store_name else None,
                "email_code_hash": hash_token(email_code),
                "mobile_code_hash": hash_token(mobile_code),
                "expires_at": now + ONE_TIME_TOKEN_TTL,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )

    email_sent, email_error = send_email_verification_code_detailed(settings, email, email_code)
    sms_sent, sms_error = await send_sms_verification_code_detailed(settings, payload.phone.strip(), mobile_code)

    if not settings.otp_expose_codes and (not email_sent or not sms_sent):
        delivery_errors: list[str] = []
        if not email_sent and email_error:
            delivery_errors.append(email_error)
        if not sms_sent and sms_error:
            delivery_errors.append(sms_error)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "OTP delivery failed. "
                + ("; ".join(delivery_errors) if delivery_errors else "Check provider configuration.")
            ),
        )

    return SignupInitiateResponse(
        message="Verification codes generated for email and mobile.",
        email=email,
        phone=payload.phone.strip(),
        expires_in_seconds=int(ONE_TIME_TOKEN_TTL.total_seconds()),
        email_verification_code=email_code if settings.otp_expose_codes else None,
        mobile_verification_code=mobile_code if settings.otp_expose_codes else None,
    )


@router.post("/signup/complete", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def complete_signup(payload: SignupCompleteRequest, request: Request):
    db = request.app.state.mongo_db
    email = payload.email.strip().lower()

    pending = await db.signup_verifications.find_one({"email": email})
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signup verification not found.")

    if _utc(pending["expires_at"]) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification codes expired. Please initiate signup again.")

    if hash_token(payload.email_code.strip()) != pending.get("email_code_hash"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email verification code.")

    if hash_token(payload.mobile_code.strip()) != pending.get("mobile_code_hash"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid mobile verification code.")

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    now = datetime.now(UTC)
    user_document = {
        "email": email,
        "password_salt": pending["password_salt"],
        "password_hash": pending["password_hash"],
        "full_name": pending.get("full_name"),
        "phone": pending.get("phone"),
        "avatar_url": None,
        "bio": None,
        "store_name": pending.get("store_name"),
        "role": pending["role"],
        "status": "active" if pending["role"] == "customer" else "pending",
        "email_verified": True,
        "mobile_verified": True,
        "created_at": now,
        "updated_at": now,
    }

    result = await db.users.insert_one(user_document)
    await db.signup_verifications.delete_one({"_id": pending["_id"]})

    created_user = await db.users.find_one({"_id": result.inserted_id})
    profile = serialize_user(created_user)

    if pending["role"] == "vendor":
        return AuthResponse(
            message="Vendor account created and pending review.",
            user=profile,
            tokens=None,
        )

    access_token, refresh_token, session_document = _build_session(result.inserted_id, pending["role"])
    await db.sessions.insert_one(session_document)

    return AuthResponse(
        message="Registration successful after email and mobile verification.",
        user=profile,
        tokens=AuthTokens(access_token=access_token, refresh_token=refresh_token, expires_in=86400),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_user(payload: RegisterRequest, request: Request):
    db = request.app.state.mongo_db
    email = payload.email.strip().lower()

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    now = datetime.now(UTC)
    password_salt, password_hash = hash_password(payload.password)
    user_document = {
        "email": email,
        "password_salt": password_salt,
        "password_hash": password_hash,
        "full_name": payload.full_name.strip() if payload.full_name else None,
        "phone": payload.phone.strip() if payload.phone else None,
        "avatar_url": None,
        "bio": None,
        "store_name": payload.store_name.strip() if payload.store_name else None,
        "role": payload.role,
        "status": "active" if payload.role == "customer" else "pending",
        "email_verified": False,
        "created_at": now,
        "updated_at": now,
    }

    result = await db.users.insert_one(user_document)
    created_user = await db.users.find_one({"_id": result.inserted_id})
    profile = serialize_user(created_user)

    if payload.role == "vendor":
        return AuthResponse(
            message="Vendor account created and pending review.",
            user=profile,
            tokens=None,
        )

    access_token, refresh_token, session_document = _build_session(result.inserted_id, payload.role)
    await db.sessions.insert_one(session_document)

    return AuthResponse(
        message="Registration successful.",
        user=profile,
        tokens=AuthTokens(access_token=access_token, refresh_token=refresh_token, expires_in=86400),
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup_user(payload: RegisterRequest, request: Request):
    """Frontend compatibility alias for /auth/register."""
    return await register_user(payload, request)


@router.post("/login", response_model=AuthResponse)
async def login_user(payload: LoginRequest, request: Request):
    db = request.app.state.mongo_db
    email = payload.email.strip().lower()
    user = await db.users.find_one({"email": email})

    if not user or not verify_password(payload.password, user["password_salt"], user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    if user.get("status") == "suspended":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is suspended.")

    if user.get("role") == "vendor" and user.get("status") == "pending":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vendor account is pending approval.")

    access_token, refresh_token, session_document = _build_session(user["_id"], user["role"])
    await db.sessions.insert_one(session_document)

    return AuthResponse(
        message="Login successful.",
        user=serialize_user(user),
        tokens=AuthTokens(access_token=access_token, refresh_token=refresh_token, expires_in=86400),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout_user(request: Request, current_user=Depends(get_current_user)):
    session = request.state.current_session
    await request.app.state.mongo_db.sessions.update_one(
        {"_id": session["_id"]},
        {"$set": {"revoked_at": datetime.now(UTC)}},
    )
    return LogoutResponse(message="Logged out successfully.")


@router.post("/refresh-token", response_model=AuthTokens)
async def refresh_token(payload: RefreshTokenRequest, request: Request):
    db = request.app.state.mongo_db
    session = await db.sessions.find_one(
        {
            "refresh_token_hash": hash_token(payload.refresh_token),
            "revoked_at": None,
        }
    )

    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    if _utc(session["refresh_expires_at"]) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired.")

    access_token, refresh_token_value, session_document = _build_session(session["user_id"], session["role"])
    await db.sessions.update_one(
        {"_id": session["_id"]},
        {
            "$set": {
                "access_token_hash": session_document["access_token_hash"],
                "refresh_token_hash": session_document["refresh_token_hash"],
                "access_expires_at": session_document["access_expires_at"],
                "refresh_expires_at": session_document["refresh_expires_at"],
            }
        },
    )

    return AuthTokens(access_token=access_token, refresh_token=refresh_token_value, expires_in=86400)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, request: Request):
    db = request.app.state.mongo_db
    user = await db.users.find_one({"email": payload.email.strip().lower()})

    if not user:
        return {"message": "If the email exists, a password reset link will be sent."}

    token, token_document = _build_one_time_token()
    token_document.update(
        {
            "user_id": user["_id"],
            "type": "password_reset",
            "expires_at": datetime.now(UTC) + PASSWORD_RESET_TOKEN_TTL,
        }
    )
    await db.password_reset_tokens.insert_one(token_document)
    return {"message": "Password reset link prepared.", "reset_token": token}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, request: Request):
    db = request.app.state.mongo_db
    token_hash = hash_token(payload.token)
    token_document = await db.password_reset_tokens.find_one(
        {
            "token_hash": token_hash,
            "consumed_at": None,
            "type": "password_reset",
        }
    )

    if not token_document or _utc(token_document["expires_at"]) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token.")

    password_salt, password_hash = hash_password(payload.new_password)
    await db.users.update_one(
        {"_id": token_document["user_id"]},
        {
            "$set": {
                "password_salt": password_salt,
                "password_hash": password_hash,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    await db.password_reset_tokens.update_one(
        {"_id": token_document["_id"]},
        {"$set": {"consumed_at": datetime.now(UTC)}},
    )

    return {"message": "Password has been reset successfully."}


@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, request: Request, current_user=Depends(get_current_user)):
    db = request.app.state.mongo_db

    if not verify_password(payload.current_password, current_user["password_salt"], current_user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")

    password_salt, password_hash = hash_password(payload.new_password)
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "password_salt": password_salt,
                "password_hash": password_hash,
                "updated_at": datetime.now(UTC),
            }
        },
    )

    return {"message": "Password updated successfully."}


@router.post("/verify-email")
async def verify_email(payload: VerifyEmailRequest, request: Request):
    db = request.app.state.mongo_db
    token_document = await db.email_verification_tokens.find_one(
        {
            "token_hash": hash_token(payload.token),
            "consumed_at": None,
            "type": "email_verification",
        }
    )

    if not token_document or _utc(token_document["expires_at"]) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token.")

    await db.users.update_one(
        {"_id": token_document["user_id"]},
        {
            "$set": {
                "email_verified": True,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    await db.email_verification_tokens.update_one(
        {"_id": token_document["_id"]},
        {"$set": {"consumed_at": datetime.now(UTC)}},
    )

    return {"message": "Email verified successfully."}


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationRequest, request: Request):
    db = request.app.state.mongo_db
    user = await db.users.find_one({"email": payload.email.strip().lower()})

    if not user:
        return {"message": "If the email exists, a verification link will be sent."}

    token, token_document = _build_one_time_token()
    token_document.update(
        {
            "user_id": user["_id"],
            "type": "email_verification",
            "expires_at": datetime.now(UTC) + ONE_TIME_TOKEN_TTL,
        }
    )
    await db.email_verification_tokens.insert_one(token_document)
    return {"message": "Verification link prepared.", "verification_token": token}


@router.get("/profile", response_model=UserProfile)
async def get_profile(current_user=Depends(get_current_user)):
    return serialize_user(current_user)


@router.put("/profile", response_model=UserProfile)
async def update_profile(payload: ProfileUpdateRequest, request: Request, current_user=Depends(get_current_user)):
    update_data = {
        "updated_at": datetime.now(UTC),
    }

    for field in ("full_name", "phone", "avatar_url", "bio", "store_name"):
        value = getattr(payload, field)
        if value is not None:
            update_data[field] = value.strip() if isinstance(value, str) else value

    await request.app.state.mongo_db.users.update_one({"_id": current_user["_id"]}, {"$set": update_data})
    updated_user = await request.app.state.mongo_db.users.find_one({"_id": current_user["_id"]})
    return serialize_user(updated_user)
