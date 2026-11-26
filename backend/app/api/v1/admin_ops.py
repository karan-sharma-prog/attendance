"""
Administrator Operations API:
Manage users, departments, subjects, and institutional verification policies.
"""
from typing import Tuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.database import get_db
from backend.app.core.security import get_password_hash
from backend.app.models.models import (
    User,
    Role,
    Department,
    Subject,
    Student,
    Teacher,
    InstitutionSetting,
    AuditLog,
)
from backend.app.api.deps import require_roles

router = APIRouter(prefix="/admin", tags=["Administration & Policies"])


class AdminCreateSubjectRequest(BaseModel):
    code: str
    name: str
    credits: int = 3
    department_code: str = "CSE"


class AdminSettingUpdateRequest(BaseModel):
    key: str
    value: str
    description: str | None = None


class AdminCreateUserRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: str
    enrollment_id: str | None = None
    department_code: str = "CSE"
    semester: int = 1


@router.get("/overview")
async def get_admin_overview(
    _: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(100))).scalars().all()
    roles_by_id = {r.id: r.name for r in (await db.execute(select(Role))).scalars().all()}
    subjects = (await db.execute(select(Subject).order_by(Subject.code))).scalars().all()
    departments = (await db.execute(select(Department).order_by(Department.code))).scalars().all()
    settings_rows = (await db.execute(select(InstitutionSetting))).scalars().all()

    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "enrollment_id": u.enrollment_id,
                "role": roles_by_id.get(u.role_id, "unknown"),
                "is_active": u.is_active,
            }
            for u in users
        ],
        "subjects": [{"id": s.id, "code": s.code, "name": s.name, "credits": s.credits} for s in subjects],
        "departments": [{"id": d.id, "code": d.code, "name": d.name} for d in departments],
        "settings": [{"key": st.key, "value": st.value, "description": st.description} for st in settings_rows],
    }


@router.post("/subjects")
async def create_subject(
    req: AdminCreateSubjectRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    dept = (await db.execute(select(Department).where(Department.code == req.department_code))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail=f"Department {req.department_code} not found.")
    existing = (await db.execute(select(Subject).where(Subject.code == req.code))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Subject {req.code} already exists.")
    subj = Subject(code=req.code, name=req.name, credits=req.credits, department_id=dept.id)
    db.add(subj)
    db.add(AuditLog(actor_id=admin_user.id, action="SUBJECT_CREATED", resource=f"subject:{req.code}"))
    await db.commit()
    await db.refresh(subj)
    return {"id": subj.id, "code": subj.code, "name": subj.name}


@router.post("/users")
async def admin_create_user(
    req: AdminCreateUserRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    if (await db.execute(select(User).where(User.email == req.email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered.")
    role = (await db.execute(select(Role).where(Role.name == req.role.lower()))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")
    dept = (await db.execute(select(Department).where(Department.code == req.department_code))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail=f"Department {req.department_code} not found.")

    usr = User(
        email=req.email,
        enrollment_id=req.enrollment_id,
        hashed_password=get_password_hash(req.password),
        full_name=req.full_name,
        role_id=role.id,
    )
    db.add(usr)
    await db.flush()

    if role.name == "student":
        db.add(
            Student(
                user_id=usr.id,
                department_id=dept.id,
                semester=req.semester,
                roll_number=req.enrollment_id or usr.id[:8],
            )
        )
    elif role.name == "teacher":
        db.add(
            Teacher(
                user_id=usr.id,
                department_id=dept.id,
                employee_code=req.enrollment_id or f"EMP-{usr.id[:6]}",
            )
        )

    db.add(AuditLog(actor_id=admin_user.id, action="USER_CREATED", resource=f"user:{req.email}"))
    await db.commit()
    return {"id": usr.id, "email": usr.email, "role": role.name}


@router.put("/settings")
async def update_institution_setting(
    req: AdminSettingUpdateRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    st = (await db.execute(select(InstitutionSetting).where(InstitutionSetting.key == req.key))).scalar_one_or_none()
    if st:
        st.value = req.value
        if req.description:
            st.description = req.description
    else:
        st = InstitutionSetting(key=req.key, value=req.value, description=req.description)
        db.add(st)
    db.add(AuditLog(actor_id=admin_user.id, action="SETTING_UPDATED", resource=req.key, details=req.value))
    await db.commit()
    return {"key": st.key, "value": st.value}
