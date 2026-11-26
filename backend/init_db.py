"""
Database Schema Migration & Initial Seeder for Neon PostgreSQL.
Creates all 19 tables, applies additive column migrations cleanly,
and seeds base roles, departments, subjects, enrollments, timetables, and test accounts.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from backend.app.core.database import get_engine, Base
from backend.app.models.models import (
    Role,
    User,
    Department,
    Subject,
    Student,
    Teacher,
    Enrollment,
    Timetable,
)
from backend.app.core.security import get_password_hash


async def _apply_additive_column_migrations(conn) -> None:
    """Safely add Phase 3/4 columns to existing Neon tables if migrating from Phase 2."""
    statements = [
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS timetable_id VARCHAR(36) REFERENCES timetables(id);",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS classroom VARCHAR(100);",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS is_paused BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS geofence_lat DOUBLE PRECISION;",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS geofence_lng DOUBLE PRECISION;",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS geofence_radius_meters DOUBLE PRECISION NOT NULL DEFAULT 150.0;",
        "ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS geofence_required BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE verification_transactions ADD COLUMN IF NOT EXISTS challenges_json TEXT;",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS biometric_status VARCHAR(30) NOT NULL DEFAULT 'NOT_REGISTERED';",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS biometric_consent_given BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS biometric_consent_at TIMESTAMP WITH TIME ZONE;",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS non_biometric_exempt BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS accommodation_reason TEXT;",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS request_type VARCHAR(20) NOT NULL DEFAULT 'INITIAL';",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS encrypted_preview_image BYTEA;",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS candidate_encrypted_embedding BYTEA;",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS embedding_ready BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS reviewed_by_id VARCHAR(36) REFERENCES users(id);",
        "ALTER TABLE face_registration_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))


async def initialize_database():
    print("[*] Connecting to Neon PostgreSQL and creating/updating schema tables...")
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_additive_column_migrations(conn)
    print("[SUCCESS] All 19 database tables & columns verified on Neon PostgreSQL!")

    async with AsyncSession(engine) as session:
        # 1. Roles
        roles_to_seed = [
            ("admin", "Institutional Authority / Administrator"),
            ("teacher", "Faculty / Course Instructor"),
            ("student", "Enrolled Academic Student"),
        ]
        created_roles = {}
        for role_name, desc in roles_to_seed:
            res = await session.execute(select(Role).where(Role.name == role_name))
            role_obj = res.scalar_one_or_none()
            if not role_obj:
                role_obj = Role(name=role_name, description=desc)
                session.add(role_obj)
                await session.flush()
                print(f"[+] Created role: {role_name}")
            created_roles[role_name] = role_obj

        # 2. Department
        dept_res = await session.execute(select(Department).where(Department.code == "CSE"))
        dept = dept_res.scalar_one_or_none()
        if not dept:
            dept = Department(name="Computer Science & Engineering", code="CSE")
            session.add(dept)
            await session.flush()
            print("[+] Created department: Computer Science & Engineering (CSE)")

        # 3. Subjects
        sample_subjects = [
            ("CS-401", "Distributed Systems & Cloud Computing", 4),
            ("CS-403", "Computer Vision & Deep Learning", 4),
            ("CS-405", "Cryptographic Engineering & Security", 3),
            ("CS-407", "Enterprise Database Systems", 4),
        ]
        subjects_map = {}
        for code, title, credits in sample_subjects:
            subj_res = await session.execute(select(Subject).where(Subject.code == code))
            subj = subj_res.scalar_one_or_none()
            if not subj:
                subj = Subject(name=title, code=code, department_id=dept.id, credits=credits)
                session.add(subj)
                await session.flush()
                print(f"[+] Created subject: {code} — {title}")
            subjects_map[code] = subj

        # 4. Administrator Account
        admin_res = await session.execute(select(User).where(User.email == "admin@smartpresence.edu"))
        if not admin_res.scalar_one_or_none():
            admin_user = User(
                email="admin@smartpresence.edu",
                enrollment_id="ADM-001",
                hashed_password=get_password_hash("AdminPass@2026"),
                full_name="Dean of Academic Affairs",
                role_id=created_roles["admin"].id,
                is_active=True,
            )
            session.add(admin_user)
            print("[+] Seeded Admin: admin@smartpresence.edu / AdminPass@2026")

        # 5. Teacher Account
        teacher_res = await session.execute(select(User).where(User.email == "faculty.vance@smartpresence.edu"))
        t_user = teacher_res.scalar_one_or_none()
        if not t_user:
            t_user = User(
                email="faculty.vance@smartpresence.edu",
                enrollment_id="FAC-1001",
                hashed_password=get_password_hash("FacultyPass@2026"),
                full_name="Prof. Dr. Vance",
                role_id=created_roles["teacher"].id,
                is_active=True,
            )
            session.add(t_user)
            await session.flush()
            t_profile = Teacher(
                user_id=t_user.id,
                department_id=dept.id,
                employee_code="EMP-CS-042",
                designation="Associate Professor",
            )
            session.add(t_profile)
            await session.flush()
            print("[+] Seeded Faculty: faculty.vance@smartpresence.edu / FacultyPass@2026")
        else:
            tp_res = await session.execute(select(Teacher).where(Teacher.user_id == t_user.id))
            t_profile = tp_res.scalar_one()

        # 6. Student Account
        student_res = await session.execute(select(User).where(User.email == "alex.rivera@smartpresence.edu"))
        s_user = student_res.scalar_one_or_none()
        if not s_user:
            s_user = User(
                email="alex.rivera@smartpresence.edu",
                enrollment_id="CS2024-8841",
                hashed_password=get_password_hash("StudentPass@2026"),
                full_name="Alex Rivera",
                role_id=created_roles["student"].id,
                is_active=True,
            )
            session.add(s_user)
            await session.flush()
            s_profile = Student(
                user_id=s_user.id,
                department_id=dept.id,
                semester=7,
                roll_number="CS2024-8841",
            )
            session.add(s_profile)
            await session.flush()
            print("[+] Seeded Student: alex.rivera@smartpresence.edu / StudentPass@2026")
        else:
            sp_res = await session.execute(select(Student).where(Student.user_id == s_user.id))
            s_profile = sp_res.scalar_one()

        # 7. Enroll Student in all 4 CSE subjects (needed for real QR enrollment validation!)
        for code, subj in subjects_map.items():
            enr_res = await session.execute(
                select(Enrollment).where(
                    Enrollment.student_id == s_profile.id,
                    Enrollment.subject_id == subj.id,
                )
            )
            if not enr_res.scalar_one_or_none():
                session.add(
                    Enrollment(
                        student_id=s_profile.id,
                        subject_id=subj.id,
                        semester=7,
                        academic_year="2026-2027",
                    )
                )
                print(f"[+] Enrolled {s_profile.roll_number} in {code}")

        # 8. Sample Timetable entry if none exists
        tt_res = await session.execute(select(Timetable).where(Timetable.teacher_id == t_profile.id))
        if not tt_res.scalars().first():
            session.add(
                Timetable(
                    subject_id=subjects_map["CS-401"].id,
                    teacher_id=t_profile.id,
                    day_of_week=3,  # Thursday
                    start_time="10:00",
                    end_time="11:00",
                    room_number="Hall 302",
                    auto_open_offset_minutes=3,
                    auto_close_offset_minutes=5,
                    qr_refresh_interval=8,
                )
            )
            print("[+] Created sample timetable slot for CS-401 (Hall 302)")

        await session.commit()
        print("[SUCCESS] Neon PostgreSQL database initialization & migration complete!")


if __name__ == "__main__":
    asyncio.run(initialize_database())
