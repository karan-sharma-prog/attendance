"""
Idempotent script to add requested student and teacher accounts to Neon PostgreSQL.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from backend.app.core.database import get_engine
from backend.app.core.security import get_password_hash
from backend.app.models.models import Role, User, Department, Subject, Student, Teacher, Enrollment


ACCOUNTS = [
    {
        "email": "karansharma042006@gmail.com",
        "password": "12345",
        "full_name": "Karan Sharma",
        "role": "student",
        "code": "CS2024-8842",
    },
    {
        "email": "nisha@gmail.com",
        "password": "12345",
        "full_name": "Nisha",
        "role": "student",
        "code": "CS2024-8843",
    },
    {
        "email": "prince@gmail.com",
        "password": "12345",
        "full_name": "Prince",
        "role": "student",
        "code": "CS2024-8844",
    },
    {
        "email": "ayush@gmail.com",
        "password": "12345",
        "full_name": "Ayush",
        "role": "student",
        "code": "CS2024-8845",
    },
    {
        "email": "shivika@gmail.com",
        "password": "teacher",
        "full_name": "Shivika",
        "role": "teacher",
        "code": "FAC-1002",
    },
]


async def add_accounts() -> None:
    engine = get_engine()
    async with AsyncSession(engine) as session:
        dept = (await session.execute(select(Department).where(Department.code == "CSE"))).scalar_one()
        subjects = (await session.execute(select(Subject))).scalars().all()
        roles = {r.name: r for r in (await session.execute(select(Role))).scalars().all()}

        for acc in ACCOUNTS:
            existing = (await session.execute(select(User).where(User.email == acc["email"]))).scalar_one_or_none()
            if existing:
                print(f"[SKIP] {acc['email']} already exists.")
                continue

            usr = User(
                email=acc["email"],
                enrollment_id=acc["code"],
                hashed_password=get_password_hash(acc["password"]),
                full_name=acc["full_name"],
                role_id=roles[acc["role"]].id,
                is_active=True,
            )
            session.add(usr)
            await session.flush()

            if acc["role"] == "student":
                stu = Student(
                    user_id=usr.id,
                    department_id=dept.id,
                    semester=7,
                    roll_number=acc["code"],
                )
                session.add(stu)
                await session.flush()
                for subj in subjects:
                    session.add(
                        Enrollment(
                            student_id=stu.id,
                            subject_id=subj.id,
                            semester=7,
                            academic_year="2026-2027",
                        )
                    )
                print(f"[+] Added student: {acc['email']} ({acc['code']}) enrolled in {len(subjects)} subjects")
            else:
                tch = Teacher(
                    user_id=usr.id,
                    department_id=dept.id,
                    employee_code=acc["code"],
                    designation="Assistant Professor",
                )
                session.add(tch)
                print(f"[+] Added teacher: {acc['email']} ({acc['code']})")

        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_accounts())
