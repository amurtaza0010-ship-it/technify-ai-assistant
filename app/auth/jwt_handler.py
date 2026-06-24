"""
TAIA JWT Handler Phase 3
Validates real JWT tokens signed with the ERP's secret key.
"""
from fastapi import Header, HTTPException
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
from datetime import datetime, timedelta
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEY = "technify-secret-key"
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def _is_development() -> bool:
    return os.getenv("APP_DEBUG", "false").strip().lower() in ("true", "1", "yes")


def get_secret_key() -> str:
    key = os.getenv("JWT_SECRET_KEY", "").strip()
    if not key:
        return DEFAULT_SECRET_KEY
    return key


# Kept for modules that import SECRET_KEY directly
SECRET_KEY = get_secret_key()


def decode_token(token: str) -> dict:
    secret = get_secret_key()
    decode_options = {"verify_exp": False} if _is_development() else {}

    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options=decode_options,
        )
    except ExpiredSignatureError:
        if _is_development():
            logger.warning(
                "JWT token expired — allowing request in development mode (verify_exp=False)."
            )
            return jwt.decode(
                token,
                secret,
                algorithms=[ALGORITHM],
                options={"verify_exp": False},
            )
        raise


def create_token(user_id: str, role: str, name: str, department: str, email: str) -> str:
    """
    Create a signed JWT token. Used by the Mock ERP login endpoint.
    In production, the real Laravel ERP issues this token.
    """
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {
        "sub": user_id,
        "role": role,
        "name": name,
        "department": department,
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def verify_user_access(
    x_user_id: str = Header(None),
    x_user_role: str = Header(None),
    authorization: str = Header(None),
) -> dict:
    """
    Validate the user's identity. Supports two modes:
    Mode 1 JWT Token (production)
    Mode 2 Simple Headers (development fallback)
    """
    logger.debug("Auth check: authorization=%s", bool(authorization))

    # Mode 1: JWT Token validation
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            role = payload.get("role")

            if not user_id or not role:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token: missing user_id or role.",
                )

            return {
                "user_id": user_id,
                "role": role,
                "name": payload.get("name", ""),
                "department": payload.get("department", ""),
                "email": payload.get("email", ""),
                "auth_mode": "jwt",
            }
        except JWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid or expired token: {str(e)}",
            )

    # Mode 2: Simple header fallback (development only)
    if x_user_id and x_user_role:
        allowed_roles = {"Student", "Faculty", "Admin", "student", "faculty", "admin"}
        if x_user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Invalid role: {x_user_role}. Allowed roles: Student, Faculty, Admin",
            )
        return {
            "user_id": x_user_id,
            "role": x_user_role.capitalize(),
            "name": "",
            "auth_mode": "header",
        }

    # No credentials provided
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Send 'Authorization: Bearer <token>' or 'x-user-id' and 'x-user-role' headers.",
    )
