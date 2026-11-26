import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.config import settings
from backend.app.core.database import get_engine, Base
from backend.app.models.models import Timetable, AttendanceSession
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.sessions import router as sessions_router
from backend.app.api.v1.verification import router as verification_router
from backend.app.api.v1.biometrics import student_router as biometrics_student_router, admin_router as biometrics_admin_router
from backend.app.api.v1.attendance import router as attendance_router
from backend.app.api.v1.analytics import router as analytics_router
from backend.app.api.v1.leave_notifications import leave_router, notif_router
from backend.app.api.v1.admin_ops import router as admin_ops_router
from backend.app.api.v1.reports import router as reports_router
from backend.app.api.websocket.live_monitor import router as ws_router
from backend.app.services.redis_service import ttl_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smartpresence.main")


async def _automatic_session_scheduler() -> None:
    """
    Lightweight background scheduler for Automatic Mode timetable sessions
    and auto-closing expired attendance windows using server UTC time.
    """
    while True:
        try:
            engine = get_engine()
            now = datetime.now(timezone.utc)
            async with AsyncSession(engine) as db:
                # 1. Close expired active sessions
                exp_res = await db.execute(
                    select(AttendanceSession).where(
                        AttendanceSession.is_active.is_(True),
                        AttendanceSession.end_time < now,
                    )
                )
                for s in exp_res.scalars().all():
                    s.is_active = False
                    s.is_paused = False
                    s.status = "CLOSED"

                # 2. Activate scheduled sessions whose start_time has arrived
                sched_res = await db.execute(
                    select(AttendanceSession).where(
                        AttendanceSession.is_active.is_(True),
                        AttendanceSession.status == "SCHEDULED",
                        AttendanceSession.start_time <= now,
                        AttendanceSession.end_time >= now,
                    )
                )
                for s in sched_res.scalars().all():
                    s.status = "ACTIVE"

                # 3. Check active timetables for today (UTC day_of_week)
                tt_res = await db.execute(
                    select(Timetable).where(
                        Timetable.is_active.is_(True),
                        Timetable.day_of_week == now.weekday(),
                    )
                )
                for tt in tt_res.scalars().all():
                    hh, mm = map(int, tt.start_time.split(":"))
                    lecture_start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    open_at = lecture_start - timedelta(minutes=tt.auto_open_offset_minutes)
                    close_at = lecture_start + timedelta(minutes=tt.auto_close_offset_minutes)
                    if open_at <= now <= close_at:
                        exists_res = await db.execute(
                            select(AttendanceSession).where(
                                AttendanceSession.timetable_id == tt.id,
                                AttendanceSession.start_time >= open_at - timedelta(minutes=1),
                            )
                        )
                        if not exists_res.scalars().first():
                            db.add(
                                AttendanceSession(
                                    subject_id=tt.subject_id,
                                    section_id=tt.section_id,
                                    teacher_id=tt.teacher_id,
                                    timetable_id=tt.id,
                                    classroom=tt.room_number,
                                    start_time=open_at,
                                    end_time=close_at,
                                    mode="AUTOMATIC",
                                    status="ACTIVE",
                                    qr_refresh_interval=tt.qr_refresh_interval,
                                    is_active=True,
                                    is_paused=False,
                                )
                            )
                await db.commit()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Scheduler tick error: %s", exc)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing SmartPresence database engine & Redis store...")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ttl_store.init()
    scheduler_task = asyncio.create_task(_automatic_session_scheduler())
    logger.info("SmartPresence startup complete.")
    yield
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await ttl_store.close()
    if engine:
        await engine.dispose()
    logger.info("Database engine and Redis store gracefully disposed.")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="SmartPresence: An AI-Integrated Attendance Management System Using Secure Dynamic QR Authentication, Facial Liveness Detection and Authority-Verified Biometric Recognition.",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(sessions_router, prefix=settings.API_V1_STR)
app.include_router(verification_router, prefix=settings.API_V1_STR)
app.include_router(biometrics_student_router, prefix=settings.API_V1_STR)
app.include_router(biometrics_admin_router, prefix=settings.API_V1_STR)
app.include_router(attendance_router, prefix=settings.API_V1_STR)
app.include_router(analytics_router, prefix=settings.API_V1_STR)
app.include_router(leave_router, prefix=settings.API_V1_STR)
app.include_router(notif_router, prefix=settings.API_V1_STR)
app.include_router(admin_ops_router, prefix=settings.API_V1_STR)
app.include_router(reports_router, prefix=settings.API_V1_STR)
app.include_router(ws_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "HEALTHY",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "redis_connected": ttl_store.is_redis_connected,
    }
