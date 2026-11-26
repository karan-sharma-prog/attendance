"""
Backend Authentication, RBAC & Rate-Limiting Dependencies.
All role permissions are enforced server-side.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Callable, Tuple
from backend.app.core.database import get_db
from backend.app.core.security import decode_token
from backend.app.models.models import User, Role
from backend.app.services.redis_service import ttl_store

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_with_role(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tuple[User, str]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") not in (None, "access"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and await ttl_store.get(f"revoked_token:{jti}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token subject.")

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account inactive or missing.")

    role_res = await db.execute(select(Role).where(Role.id == user.role_id))
    role_obj = role_res.scalar_one_or_none()
    role_name = role_obj.name if role_obj else "student"

    return user, role_name


def require_roles(*allowed_roles: str) -> Callable:
    async def role_checker(
        user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    ) -> Tuple[User, str]:
        user, role_name = user_and_role
        if role_name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {', '.join(allowed_roles)}.",
            )
        return user, role_name

    return role_checker


async def check_rate_limit(request: Request, action: str, max_requests: int = 30, window_seconds: int = 60) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"rl:{action}:{client_ip}"
    count = await ttl_store.incr_window(key, window_seconds)
    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {action}. Please wait and try again.",
        )
