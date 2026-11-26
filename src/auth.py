"""Employee-only JWT authentication and shared CRM/Supabase role guard."""

import base64
import hashlib
import hmac
import json
import time
from typing import Optional
from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from src.config import CRM_JWT_SECRET, SUPABASE_JWT_SECRET

ALLOWED_CRM_ROLES = {"employee", "admin"}


class AuthenticatedUser(BaseModel):
    """Verified CRM user extracted from JWT."""

    user_id: str
    role: str
    email: Optional[str] = None


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_signing_secret(secret: Optional[str] = None) -> bytes:
    return (secret or SUPABASE_JWT_SECRET or CRM_JWT_SECRET).encode("utf-8")


def create_crm_token(
    user_id: str,
    role: str,
    email: Optional[str] = None,
    expires_in: int = 3600,
    secret: Optional[str] = None,
) -> str:
    """Create a signed HS256 CRM JWT token."""
    signing_secret = _get_signing_secret(secret)
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + expires_in,
    }
    if email:
        payload["email"] = email

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(signing_secret, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_crm_token(token: str, secret: Optional[str] = None) -> AuthenticatedUser:
    """Verify HS256 CRM or Supabase JWT signature, expiration, and role."""
    signing_secret = _get_signing_secret(secret)
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT token.")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(signing_secret, signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid JWT signature.")

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        raise ValueError("JWT token has expired.")

    user_id = payload.get("sub") or payload.get("user_id")
    app_meta = payload.get("app_metadata") or {}
    user_meta = payload.get("user_metadata") or {}
    raw_role = (
        payload.get("crm_role")
        or app_meta.get("role")
        or user_meta.get("role")
        or payload.get("role", "")
    )
    role = str(raw_role).lower().strip()
    if not user_id or not role:
        raise ValueError("JWT payload missing required 'sub' or 'role'.")

    return AuthenticatedUser(user_id=str(user_id), role=role, email=payload.get("email"))


def require_employee_user(
    authorization: Optional[str] = Header(default=None),
) -> AuthenticatedUser:
    """FastAPI dependency enforcing employee-only access (blocks clients and anonymous callers)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing Bearer token.",
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        user = verify_crm_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired CRM token: {exc}",
        ) from exc

    if user.role not in ALLOWED_CRM_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: ScriptFalcon is restricted to VG Digital Falcon employees.",
        )

    return user
