from fastapi import Depends, HTTPException
from app.auth.jwt_handler import verify_user_access

class RoleChecker:
    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    def __call__(self, user: dict = Depends(verify_user_access)):
        user_role = user.get("role", "").lower()
        allowed_lower = [r.lower() for r in self.allowed_roles]

        # Explicit admin access for audit and admin-only endpoints
        if user_role == "admin" and "admin" in allowed_lower:
            return user

        if user_role not in allowed_lower:
            raise HTTPException(
                status_code=403,
                detail="Access denied. You do not have permission to access this resource!",
            )
        return user