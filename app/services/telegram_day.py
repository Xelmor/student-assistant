"""Shared effective day and lesson timing for Telegram schedule views."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil

from sqlalchemy.orm import Session

from ..models import ScheduleItem, User
from .calendar_service import build_calendar_event_map, should_show_schedule_on_day


LESSON_TYPES = {'schedule', 'schedule-change'}


def format_interval(interval: timedelta) -> str:
    """Round positive remainders up so 20 seconds never reads '0 мин'."""
    minutes = max(0, ceil(interval.total_seconds() / 60))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f'{minutes} мин'
    return f'{hours} ч {minutes} мин' if minutes else f'{hours} ч'


def has_complete_time(lesson: dict) -> bool:
    return lesson['end'] > lesson['start'] and (
        lesson['type'] != 'schedule-change'
        or bool(lesson.get('raw_start_time') and lesson.get('raw_end_time'))
    )


@dataclass
class DaySchedule:
    lessons: list[dict]
    current: dict | None
    upcoming: dict | None
    status: str


class TelegramCalendar:
    """Request-local cache; subsequent requests always read the database again."""

    def __init__(self, db: Session, user: User, local_now: datetime):
        self.db = db
        self.user = user
        self.now = local_now.replace(tzinfo=None)
        self.today = self.now.date()
        self._months = {}

    def events_on(self, day: date) -> list[dict]:
        period = (day.year, day.month)
        if period not in self._months:
            self._months[period] = build_calendar_event_map(self.user, self.db, *period)['event_map']
        return self._months[period].get(day, [])

    def day(self, day: date | None = None) -> DaySchedule:
        lessons = [event for event in self.events_on(day or self.today) if event['type'] in LESSON_TYPES]
        if any(not has_complete_time(lesson) for lesson in lessons):
            return DaySchedule(lessons, None, None, 'incomplete')
        current = next((lesson for lesson in lessons if lesson['start'] <= self.now < lesson['end']), None)
        upcoming = next((lesson for lesson in lessons if lesson['start'] > self.now), None)
        if current:
            status = 'current'
        elif upcoming:
            status = 'before' if self.now < lessons[0]['start'] else 'gap'
        else:
            status = 'finished' if lessons else 'empty'
        return DaySchedule(lessons, current, upcoming, status)

    def cancelled_today(self) -> list[ScheduleItem]:
        # The calendar has already decided that the day is overridden. Read the
        # regular slots only to label their cancellation in the expanded view.
        if not any(event['type'] == 'override' for event in self.events_on(self.today)):
            return []
        if not should_show_schedule_on_day(self.user, self.today):
            return []
        return self.db.query(ScheduleItem).filter(
            ScheduleItem.user_id == self.user.id,
            ScheduleItem.weekday == self.today.weekday(),
        ).order_by(ScheduleItem.start_time, ScheduleItem.id).all()
