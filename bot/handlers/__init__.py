from aiogram import Dispatcher

from .common import router as common_router
from .login import router as login_router
from .reminders import router as reminders_router
from .tasks import router as tasks_router


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(login_router)
    dp.include_router(tasks_router)
    dp.include_router(reminders_router)
    dp.include_router(common_router)
