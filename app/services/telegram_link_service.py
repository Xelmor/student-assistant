from __future__ import annotations

import secrets
from datetime import timedelta

from ..core.time import current_time


def generate_telegram_link_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def assign_telegram_link_code(user, ttl_minutes: int) -> str:
    code = generate_telegram_link_code()
    user.telegram_link_code = code
    user.telegram_link_code_expires_at = current_time().replace(tzinfo=None) + timedelta(minutes=ttl_minutes)
    return code


def telegram_link_code_is_active(user) -> bool:
    if not user.telegram_link_code or not user.telegram_link_code_expires_at:
        return False
    return user.telegram_link_code_expires_at >= current_time().replace(tzinfo=None)

