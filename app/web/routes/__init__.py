from fastapi import APIRouter

from .auth import router as auth_router
from .calendar import router as calendar_router
from .dashboard import router as dashboard_router
from .data import router as data_router
from .notes import router as notes_router
from .profile import router as profile_router
from .schedule import router as schedule_router
from .subjects import router as subjects_router
from .tasks import router as tasks_router


router = APIRouter()
router.include_router(auth_router)
router.include_router(profile_router)
router.include_router(data_router)
router.include_router(dashboard_router)
router.include_router(calendar_router)
router.include_router(subjects_router)
router.include_router(tasks_router)
router.include_router(schedule_router)
router.include_router(notes_router)
