import calendar
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import ScheduleItem, Task, User
from ..settings import settings
from ..utils import current_date, current_time
from .common import get_schedule_terms

APP_TIMEZONE = settings.timezone
VIEW_MODE_OPTIONS = {'month', 'week'}

MONTH_NAMES_RU = {
    1: 'Январь',
    2: 'Февраль',
    3: 'Март',
    4: 'Апрель',
    5: 'Май',
    6: 'Июнь',
    7: 'Июль',
    8: 'Август',
    9: 'Сентябрь',
    10: 'Октябрь',
    11: 'Ноябрь',
    12: 'Декабрь',
}


def normalize_calendar_period(year: int | None, month: int | None):
    today = current_date()
    safe_year = year or today.year
    safe_month = month or today.month

    if safe_month < 1:
        safe_month = 1
    if safe_month > 12:
        safe_month = 12

    return safe_year, safe_month


def shift_calendar_period(year: int, month: int, delta: int):
    month_index = (year * 12 + (month - 1)) + delta
    return month_index // 12, month_index % 12 + 1


def iso_date_or_none(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def format_calendar_badge(event_type: str, priority: str | None = None):
    if event_type == 'task':
        if priority == 'high':
            return 'Высокий приоритет'
        if priority == 'low':
            return 'Низкий приоритет'
        return 'Дедлайн'
    return 'Пара'


def get_event_weight(day_events):
    score = 0
    for event in day_events:
        if event['type'] == 'task':
            score += 3 if event.get('priority') == 'high' else 2
        else:
            score += 1
    return score


def get_intensity_level(day_events):
    weight = get_event_weight(day_events)
    if weight >= 7:
        return 4
    if weight >= 5:
        return 3
    if weight >= 3:
        return 2
    if weight >= 1:
        return 1
    return 0


def build_day_snapshot(day: date, day_events, current_month: int | None = None):
    today = current_date()
    schedule_events = [event for event in day_events if event['type'] == 'schedule']
    task_events = [event for event in day_events if event['type'] == 'task']
    first_schedule_start = schedule_events[0]['start'].strftime('%H:%M') if schedule_events else None
    last_schedule_end = schedule_events[-1]['end'].strftime('%H:%M') if schedule_events else None
    return {
        'date': day,
        'iso_date': day.isoformat(),
        'day': day.day,
        'in_month': current_month is None or day.month == current_month,
        'is_today': day == today,
        'event_count': len(day_events),
        'has_task': bool(task_events),
        'has_schedule': bool(schedule_events),
        'has_overdue': any(event['is_overdue'] for event in day_events),
        'task_count': len(task_events),
        'schedule_count': len(schedule_events),
        'first_schedule_start': first_schedule_start,
        'last_schedule_end': last_schedule_end,
        'first_schedule_index': 1 if schedule_events else None,
        'last_schedule_index': len(schedule_events) if schedule_events else None,
        'intensity': get_intensity_level(day_events),
    }


def build_calendar_event_map(user: User, db: Session, year: int, month: int):
    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    visible_dates = [day for week in month_matrix for day in week]
    visible_start = visible_dates[0]
    visible_end = visible_dates[-1]

    tasks = db.query(Task).filter(
        Task.user_id == user.id,
        Task.deadline.isnot(None),
    ).all()

    schedule_items = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user.id,
    ).order_by(ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()).all()

    event_map = {day: [] for day in visible_dates}

    for task in tasks:
        deadline_date = task.deadline.date()
        if visible_start <= deadline_date <= visible_end:
            event_map.setdefault(deadline_date, []).append(
                {
                    'type': 'task',
                    'title': task.title,
                    'subject': task.subject.name if task.subject else None,
                    'start': task.deadline,
                    'end': task.deadline + timedelta(hours=1),
                    'time_label': task.deadline.strftime('%H:%M'),
                    'meta': task.subject.name if task.subject else 'Без предмета',
                    'badge': format_calendar_badge('task', task.priority),
                    'priority': task.priority,
                    'is_completed': task.is_completed,
                    'is_overdue': (not task.is_completed) and task.deadline < current_time().replace(tzinfo=None),
                    'description': task.description or '',
                    'room': None,
                }
            )

    current_date = visible_start
    while current_date <= visible_end:
        matching_items = [item for item in schedule_items if item.weekday == current_date.weekday()]
        for item in matching_items:
            start_dt = datetime.combine(current_date, item.start_time)
            end_dt = datetime.combine(current_date, item.end_time)
            event_map.setdefault(current_date, []).append(
                {
                    'type': 'schedule',
                    'title': item.subject.name,
                    'subject': item.subject.name,
                    'start': start_dt,
                    'end': end_dt,
                    'time_label': f"{item.start_time.strftime('%H:%M')} - {item.end_time.strftime('%H:%M')}",
                    'meta': item.lesson_type or 'Занятие',
                    'badge': format_calendar_badge('schedule'),
                    'priority': None,
                    'is_completed': False,
                    'is_overdue': False,
                    'description': item.lesson_type or '',
                    'room': item.room,
                }
            )
        current_date += timedelta(days=1)

    for day_events in event_map.values():
        day_events.sort(key=lambda event: event['start'])

    weeks = []
    for week in month_matrix:
        week_cells = []
        for day in week:
            week_cells.append(build_day_snapshot(day, event_map.get(day, []), month))
        weeks.append(week_cells)

    return {
        'weeks': weeks,
        'event_map': event_map,
        'visible_start': visible_start,
        'visible_end': visible_end,
    }


def build_week_days(event_map, selected_date: date):
    week_start = selected_date - timedelta(days=selected_date.weekday())
    week_days = []
    for offset in range(7):
        current_day = week_start + timedelta(days=offset)
        day_events = event_map.get(current_day, [])
        snapshot = build_day_snapshot(current_day, day_events)
        snapshot['events'] = day_events
        snapshot['is_selected'] = current_day == selected_date
        week_days.append(snapshot)
    return week_days


def summarize_selected_day(selected_events):
    task_count = sum(1 for event in selected_events if event['type'] == 'task')
    schedule_count = sum(1 for event in selected_events if event['type'] == 'schedule')
    first_event_time = selected_events[0]['start'].strftime('%H:%M') if selected_events else None
    last_event_time = selected_events[-1]['end'].strftime('%H:%M') if selected_events else None
    weight = get_event_weight(selected_events)
    return {
        'event_count': len(selected_events),
        'task_count': task_count,
        'schedule_count': schedule_count,
        'first_event_time': first_event_time,
        'last_event_time': last_event_time,
        'load_label': (
            'Высокая нагрузка' if weight >= 7
            else 'Средняя нагрузка' if weight >= 3
            else 'Легкий день' if selected_events
            else 'Свободный день'
        ),
    }


def build_upcoming_events(event_map, selected_date: date, limit: int = 6):
    upcoming = []
    now = current_time().replace(tzinfo=None)
    for day in sorted(day for day in event_map.keys() if day >= selected_date):
        for event in event_map[day]:
            if event['end'] < now:
                continue
            upcoming.append(
                {
                    'date': day,
                    'weekday': day.weekday(),
                    **event,
                }
            )
            if len(upcoming) >= limit:
                return upcoming
    return upcoming


def build_period_navigation(selected_date: date, view_mode: str):
    if view_mode == 'week':
        week_start = selected_date - timedelta(days=selected_date.weekday())
        week_end = week_start + timedelta(days=6)
        previous_date = selected_date - timedelta(days=7)
        next_date = selected_date + timedelta(days=7)
        return {
            'previous_year': previous_date.year,
            'previous_month': previous_date.month,
            'previous_selected': previous_date.isoformat(),
            'next_year': next_date.year,
            'next_month': next_date.month,
            'next_selected': next_date.isoformat(),
            'period_label': f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m')}",
            'period_kind': 'Неделя',
        }

    previous_year, previous_month = shift_calendar_period(selected_date.year, selected_date.month, -1)
    next_year, next_month = shift_calendar_period(selected_date.year, selected_date.month, 1)
    return {
        'previous_year': previous_year,
        'previous_month': previous_month,
        'previous_selected': None,
        'next_year': next_year,
        'next_month': next_month,
        'next_selected': None,
        'period_label': f"{MONTH_NAMES_RU[selected_date.month]} {selected_date.year}",
        'period_kind': 'Месяц',
    }


def build_calendar_page_context(
    user: User,
    db: Session,
    year: int | None = None,
    month: int | None = None,
    selected_date_raw: str | None = None,
    view_mode: str = 'month',
):
    safe_year, safe_month = normalize_calendar_period(year, month)
    month_context = build_calendar_event_map(user, db, safe_year, safe_month)
    schedule_terms = get_schedule_terms(user)
    safe_view_mode = view_mode if view_mode in VIEW_MODE_OPTIONS else 'month'
    selected_date = iso_date_or_none(selected_date_raw)
    if selected_date is None or selected_date not in month_context['event_map']:
        today = current_date()
        if today in month_context['event_map'] and today.month == safe_month and today.year == safe_year:
            selected_date = today
        else:
            selected_date = next(iter(month_context['event_map'].keys()))

    selected_events = month_context['event_map'].get(selected_date, [])
    weekly_schedule_count = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).count()
    week_days = build_week_days(month_context['event_map'], selected_date)
    upcoming_events = build_upcoming_events(month_context['event_map'], selected_date)
    selected_summary = summarize_selected_day(selected_events)
    navigation = build_period_navigation(selected_date, safe_view_mode)

    busiest_day = max(
        (
            build_day_snapshot(day, events, safe_month)
            for day, events in month_context['event_map'].items()
            if day.month == safe_month
        ),
        key=lambda snapshot: (snapshot['intensity'], snapshot['event_count']),
        default=None,
    )

    return {
        'calendar_year': safe_year,
        'calendar_month': safe_month,
        'calendar_label': f"{MONTH_NAMES_RU[safe_month]} {safe_year}",
        'calendar_weeks': month_context['weeks'],
        'selected_date': selected_date,
        'selected_iso': selected_date.isoformat(),
        'selected_events': selected_events,
        'previous_year': navigation['previous_year'],
        'previous_month': navigation['previous_month'],
        'previous_selected': navigation['previous_selected'],
        'next_year': navigation['next_year'],
        'next_month': navigation['next_month'],
        'next_selected': navigation['next_selected'],
        'period_label': navigation['period_label'],
        'period_kind': navigation['period_kind'],
        'month_task_count': sum(1 for events in month_context['event_map'].values() for event in events if event['type'] == 'task'),
        'month_schedule_count': sum(1 for events in month_context['event_map'].values() for event in events if event['type'] == 'schedule'),
        'weekly_schedule_count': weekly_schedule_count,
        'schedule_terms': schedule_terms,
        'view_mode': safe_view_mode,
        'week_days': week_days,
        'selected_summary': selected_summary,
        'upcoming_events': upcoming_events,
        'busiest_day': busiest_day,
    }


def escape_ics_text(value: str | None):
    if not value:
        return ''
    return (
        value.replace('\\', '\\\\')
        .replace(';', r'\;')
        .replace(',', r'\,')
        .replace('\n', r'\n')
    )


def format_ics_datetime(value: datetime):
    return value.strftime('%Y%m%dT%H%M%S')


def build_ics_calendar(user: User, db: Session, year: int | None = None, month: int | None = None):
    context = build_calendar_page_context(user, db, year, month, None)
    safe_year = context['calendar_year']
    safe_month = context['calendar_month']
    event_map = build_calendar_event_map(user, db, safe_year, safe_month)['event_map']

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Student Assistant//Calendar Export//RU',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:Student Assistant {safe_month:02d}/{safe_year}',
        f'X-WR-TIMEZONE:{APP_TIMEZONE}',
    ]

    for day, events in sorted(event_map.items(), key=lambda item: item[0]):
        for index, event in enumerate(events, start=1):
            location_parts = [event['room']] if event['room'] else []
            if event['subject'] and event['type'] == 'task':
                location_parts.append(event['subject'])
            description_parts = [event['meta']]
            if event['description']:
                description_parts.append(event['description'])
            summary = event['title']
            if event['type'] == 'task':
                summary = f'Дедлайн: {summary}'

            lines.extend([
                'BEGIN:VEVENT',
                f'UID:{event["type"]}-{day.isoformat()}-{index}-{user.id}@student-assistant',
                f'DTSTAMP:{format_ics_datetime(datetime.utcnow())}Z',
                f'DTSTART;TZID={APP_TIMEZONE}:{format_ics_datetime(event["start"])}',
                f'DTEND;TZID={APP_TIMEZONE}:{format_ics_datetime(event["end"])}',
                f'SUMMARY:{escape_ics_text(summary)}',
                f'DESCRIPTION:{escape_ics_text(" | ".join(part for part in description_parts if part))}',
                f'LOCATION:{escape_ics_text(", ".join(part for part in location_parts if part))}',
                'END:VEVENT',
            ])

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines).encode('utf-8')
