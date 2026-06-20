"""JWT Validator Middleware — verifies the Authorization Bearer token on every request."""
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-from-erp")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Paths that don't require a valid JWT
PUBLIC_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/api/v1/auth/login"}


class JWTValidatorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Authorization token missing!"})

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token!"})

        request.state.user = payload
        return await call_next(request)
