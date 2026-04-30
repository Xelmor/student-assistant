from __future__ import annotations

from datetime import datetime, timedelta

RECURRENCE_NONE = 'none'
RECURRENCE_DAILY = 'daily'
RECURRENCE_WEEKLY = 'weekly'
RECURRENCE_CUSTOM_DAYS = 'custom_days'

RECURRENCE_OPTIONS = {
    RECURRENCE_NONE: 'Не повторять',
    RECURRENCE_DAILY: 'Каждый день',
    RECURRENCE_WEEKLY: 'Каждую неделю',
    RECURRENCE_CUSTOM_DAYS: 'Каждые N дней',
}


def normalize_recurrence_settings(
    recurrence_type: str | None,
    recurrence_interval_days: str | int | None,
) -> tuple[str, int | None]:
    normalized_type = (recurrence_type or RECURRENCE_NONE).strip().lower()
    if normalized_type not in RECURRENCE_OPTIONS:
        normalized_type = RECURRENCE_NONE

    if normalized_type != RECURRENCE_CUSTOM_DAYS:
        return normalized_type, None

    raw_interval = str(recurrence_interval_days or '').strip()
    if not raw_interval:
        raise ValueError('Для повтора по интервалу укажи количество дней.')

    try:
        interval_value = int(raw_interval)
    except ValueError as error:
        raise ValueError('Интервал повторения должен быть целым числом.') from error

    if interval_value < 2 or interval_value > 365:
        raise ValueError('Интервал повторения должен быть от 2 до 365 дней.')

    return normalized_type, interval_value


def recurrence_requires_deadline(recurrence_type: str) -> bool:
    return recurrence_type != RECURRENCE_NONE


def get_recurrence_label(recurrence_type: str, recurrence_interval_days: int | None) -> str | None:
    if recurrence_type == RECURRENCE_NONE:
        return None
    if recurrence_type == RECURRENCE_DAILY:
        return 'Каждый день'
    if recurrence_type == RECURRENCE_WEEKLY:
        return 'Каждую неделю'
    if recurrence_type == RECURRENCE_CUSTOM_DAYS and recurrence_interval_days:
        return f'Каждые {recurrence_interval_days} дн.'
    return None


def calculate_next_deadline(
    deadline: datetime | None,
    recurrence_type: str,
    recurrence_interval_days: int | None,
) -> datetime | None:
    if recurrence_type == RECURRENCE_NONE or deadline is None:
        return None
    if recurrence_type == RECURRENCE_DAILY:
        return deadline + timedelta(days=1)
    if recurrence_type == RECURRENCE_WEEKLY:
        return deadline + timedelta(days=7)
    if recurrence_type == RECURRENCE_CUSTOM_DAYS and recurrence_interval_days:
        return deadline + timedelta(days=recurrence_interval_days)
    return None
