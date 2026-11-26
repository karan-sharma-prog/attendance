from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Tuple
from backend.app.core.database import get_db
from backend.app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.app.models.models import User, Role, Student, Teacher, AuditLog
from backend.app.schemas.schemas import (
    Token,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    UserCreate,
    UserResponse,
)
from backend.app.api.deps import get_current_user_with_role, check_rate_limit, bearer_scheme
from backend.app.services.redis_service import ttl_store
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/auth", tags=["Authentication & RBAC"])


async def _resolve_profile_ids(user: User, role_name: str, db: AsyncSession) -> Tuple[str | None, str | None]:
    student_id = None
    teacher_id = None
    if role_name == "student":
        s_res = await db.execute(select(Student).where(Student.user_id == user.id))
        s = s_res.scalar_one_or_none()
        student_id = s.id if s else None
    elif role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        t = t_res.scalar_one_or_none()
        teacher_id = t.id if t else None
    return student_id, teacher_id


@router.post("/login", response_model=Token)
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    await check_rate_limit(request, "login", max_requests=20, window_seconds=60)

    query = select(User).where(
        (User.email == req.identifier) | (User.enrollment_id == req.identifier)
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials: Email/Enrollment ID or password does not match",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one_or_none()
    role_name = role.name if role else "student"
    student_id, teacher_id = await _resolve_profile_ids(user, role_name, db)

    access_token = create_access_token(data={"sub": user.id, "email": user.email, "role": role_name})
    refresh_token = create_refresh_token(data={"sub": user.id, "role": role_name})

    db.add(
        AuditLog(
            actor_id=user.id,
            action="LOGIN_SUCCESS",
            resource="auth",
            details=f"Role={role_name}",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        role=role_name,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        student_id=student_id,
        teacher_id=teacher_id,
    )


@router.post("/refresh", response_model=Token)
async def refresh_tokens(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    jti = payload.get("jti")
    if jti and await ttl_store.get(f"revoked_token:{jti}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has already been rotated or revoked.")

    user_id = payload.get("sub")
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account inactive or missing.")

    role_res = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_res.scalar_one_or_none()
    role_name = role.name if role else "student"
    student_id, teacher_id = await _resolve_profile_ids(user, role_name, db)

    # Rotate: revoke used refresh token JTI
    if jti:
        await ttl_store.set_ex(f"revoked_token:{jti}", 7 * 24 * 3600, "1")

    new_access = create_access_token(data={"sub": user.id, "email": user.email, "role": role_name})
    new_refresh = create_refresh_token(data={"sub": user.id, "role": role_name})

    return Token(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        role=role_name,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        student_id=student_id,
        teacher_id=teacher_id,
    )


@router.post("/logout")
async def logout(
    req: LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
):
    user, _ = user_and_role
    if credentials and credentials.credentials:
        access_payload = decode_token(credentials.credentials)
        if access_payload and access_payload.get("jti"):
            await ttl_store.set_ex(f"revoked_token:{access_payload['jti']}", 3600, "1")

    if req.refresh_token:
        refresh_payload = decode_token(req.refresh_token)
        if refresh_payload and refresh_payload.get("jti"):
            await ttl_store.set_ex(f"revoked_token:{refresh_payload['jti']}", 7 * 24 * 3600, "1")

    return {"status": "LOGGED_OUT", "user_id": user.id}


@router.get("/me", response_model=UserResponse)
async def get_me(
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    student_id, teacher_id = await _resolve_profile_ids(user, role_name, db)
    return UserResponse(
        id=user.id,
        email=user.email,
        enrollment_id=user.enrollment_id,
        full_name=user.full_name,
        role=role_name,
        is_active=user.is_active,
        created_at=user.created_at,
        student_id=student_id,
        teacher_id=teacher_id,
    )


@router.post("/register", response_model=UserResponse)
async def register(
    user_in: UserCreate,
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    _, caller_role = user_and_role
    if caller_role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can register institutional accounts.")

    existing_user = await db.execute(select(User).where(User.email == user_in.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User with this email already exists")

    role_res = await db.execute(select(Role).where(Role.name == user_in.role.lower()))
    role = role_res.scalar_one_or_none()
    if not role:
        role = Role(name=user_in.role.lower(), description=f"{user_in.role.capitalize()} Role")
        db.add(role)
        await db.flush()

    new_user = User(
        email=user_in.email,
        enrollment_id=user_in.enrollment_id,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role_id=role.id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return UserResponse(
        id=new_user.id,
        email=new_user.email,
        enrollment_id=new_user.enrollment_id,
        full_name=new_user.full_name,
        role=role.name,
        is_active=new_user.is_active,
        created_at=new_user.created_at,
    )
