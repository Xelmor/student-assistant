import calendar
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import current_date, current_time
from ..models import AcademicEvent, ScheduleItem, Subject, Task, User
from ..services.task_schedule_links import get_task_calendar_event
from ..web.dependencies import get_schedule_terms

APP_TIMEZONE = settings.timezone
VIEW_MODE_OPTIONS = {'month', 'week'}
TIMELINE_START_HOUR = 8
TIMELINE_END_HOUR = 20
ACADEMIC_EVENT_TYPE_LABELS = {
    'exam': 'Экзамен',
    'credit': 'Зачет',
    'consultation': 'Консультация',
    'resit': 'Пересдача',
    'changed_class': 'Разовая пара',
    'day_override': 'Особый день',
}
DAY_OVERRIDE_EVENT_TYPE = 'day_override'
SCHEDULE_CHANGE_EVENT_TYPES = {'changed_class'}
SESSION_EVENT_TYPES = {
    key: label
    for key, label in ACADEMIC_EVENT_TYPE_LABELS.items()
    if key not in {DAY_OVERRIDE_EVENT_TYPE, *SCHEDULE_CHANGE_EVENT_TYPES}
}
CALENDAR_EVENT_TYPE_OPTIONS = [
    {'value': 'changed_class', 'label': ACADEMIC_EVENT_TYPE_LABELS['changed_class']},
    {'value': 'exam', 'label': ACADEMIC_EVENT_TYPE_LABELS['exam']},
    {'value': 'credit', 'label': ACADEMIC_EVENT_TYPE_LABELS['credit']},
    {'value': 'consultation', 'label': ACADEMIC_EVENT_TYPE_LABELS['consultation']},
    {'value': 'resit', 'label': ACADEMIC_EVENT_TYPE_LABELS['resit']},
]

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
MONTH_NAMES_RU_GENITIVE = {
    1: 'января',
    2: 'февраля',
    3: 'марта',
    4: 'апреля',
    5: 'мая',
    6: 'июня',
    7: 'июля',
    8: 'августа',
    9: 'сентября',
    10: 'октября',
    11: 'ноября',
    12: 'декабря',
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
    if event_type == 'academic':
        return 'Сессия'
    if event_type == 'schedule-change':
        return 'Изменение'
    if event_type == 'override':
        return 'Особый день'
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
        elif event['type'] == 'academic':
            score += 4
        elif event['type'] == 'schedule-change':
            score += 2
        elif event['type'] == 'override':
            score += 1
        else:
            score += 1
    return score


def is_summer_break_day(day: date) -> bool:
    return day.month in {6, 7, 8}


def should_show_schedule_on_day(user: User, day: date) -> bool:
    last_study_day = getattr(user, 'last_study_day', None)
    if last_study_day:
        summer_break_end = date(last_study_day.year, 8, 31)
        if last_study_day < day <= summer_break_end:
            return False
        return True

    return not is_summer_break_day(day)


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
    schedule_events = [event for event in day_events if event['type'] in {'schedule', 'schedule-change'}]
    task_events = [event for event in day_events if event['type'] == 'task']
    academic_events = [event for event in day_events if event['type'] == 'academic']
    schedule_change_events = [event for event in day_events if event['type'] == 'schedule-change']
    override_events = [event for event in day_events if event['type'] == 'override']
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
        'has_academic': bool(academic_events),
        'has_schedule': bool(schedule_events),
        'has_schedule_change': bool(schedule_change_events),
        'has_override': bool(override_events),
        'has_overdue': any(event['is_overdue'] for event in day_events),
        'task_count': len(task_events),
        'academic_count': len(academic_events),
        'schedule_count': len(schedule_events),
        'schedule_change_count': len(schedule_change_events),
        'override_count': len(override_events),
        'first_schedule_start': first_schedule_start,
        'last_schedule_end': last_schedule_end,
        'first_schedule_index': 1 if schedule_events else None,
        'last_schedule_index': len(schedule_events) if schedule_events else None,
        'intensity': get_intensity_level(day_events),
    }


def format_academic_time_label(academic_event: AcademicEvent):
    if academic_event.start_time and academic_event.end_time:
        return f"{academic_event.start_time.strftime('%H:%M')} - {academic_event.end_time.strftime('%H:%M')}"
    if academic_event.start_time:
        return academic_event.start_time.strftime('%H:%M')
    if academic_event.event_type == DAY_OVERRIDE_EVENT_TYPE:
        return 'Весь день'
    return 'Без времени'


def build_academic_calendar_event(academic_event: AcademicEvent, now: datetime):
    event_start_time = academic_event.start_time or datetime.min.time()
    if academic_event.event_type == DAY_OVERRIDE_EVENT_TYPE:
        event_end_time = academic_event.end_time or datetime.max.time().replace(microsecond=0)
    else:
        event_end_time = academic_event.end_time or academic_event.start_time or event_start_time

    event_start = datetime.combine(academic_event.event_date, event_start_time)
    event_end = datetime.combine(academic_event.event_date, event_end_time)
    event_kind = ACADEMIC_EVENT_TYPE_LABELS.get(academic_event.event_type, 'Событие')
    subject_name = academic_event.subject.name if academic_event.subject else None
    event_type = 'academic'
    priority = 'high'

    if academic_event.event_type in SCHEDULE_CHANGE_EVENT_TYPES:
        event_type = 'schedule-change'
        priority = None
    elif academic_event.event_type == DAY_OVERRIDE_EVENT_TYPE:
        event_type = 'override'
        priority = None

    return {
        'type': event_type,
        'event_type': academic_event.event_type,
        'title': academic_event.title,
        'subject': subject_name,
        'subject_id': academic_event.subject_id,
        'start': event_start,
        'end': event_end,
        'time_label': format_academic_time_label(academic_event),
        'meta': 'Расписание заменено' if academic_event.event_type == DAY_OVERRIDE_EVENT_TYPE else event_kind,
        'badge': event_kind,
        'priority': priority,
        'is_completed': False,
        'is_overdue': event_end < now,
        'is_all_day': academic_event.event_type == DAY_OVERRIDE_EVENT_TYPE,
        'description': academic_event.description or '',
        'room': academic_event.room,
        'task_id': None,
        'academic_event_id': academic_event.id,
        'raw_date': academic_event.event_date.isoformat(),
        'raw_start_time': academic_event.start_time.strftime('%H:%M') if academic_event.start_time else '',
        'raw_end_time': academic_event.end_time.strftime('%H:%M') if academic_event.end_time else '',
    }


def build_calendar_event_map(user: User, db: Session, year: int, month: int):
    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    visible_dates = [day for week in month_matrix for day in week]
    visible_start = visible_dates[0]
    visible_end = visible_dates[-1]

    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    schedule_items = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user.id,
    ).order_by(ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()).all()
    academic_events = db.query(AcademicEvent).filter(
        AcademicEvent.user_id == user.id,
        AcademicEvent.event_date >= visible_start,
        AcademicEvent.event_date <= visible_end,
    ).all()
    override_dates = {
        event.event_date
        for event in academic_events
        if event.event_type == DAY_OVERRIDE_EVENT_TYPE
    }

    event_map = {day: [] for day in visible_dates}
    now = current_time()

    for task in tasks:
        task_event = get_task_calendar_event(task, now)
        if not task_event:
            continue
        event_date = task_event['date']
        if visible_start <= event_date <= visible_end:
            if not task_event.get('badge'):
                task_event['badge'] = format_calendar_badge('task', task.priority)
            event_map.setdefault(event_date, []).append(task_event)

    current_day = visible_start
    while current_day <= visible_end:
        if current_day in override_dates or not should_show_schedule_on_day(user, current_day):
            current_day += timedelta(days=1)
            continue

        matching_items = [item for item in schedule_items if item.weekday == current_day.weekday()]
        for item in matching_items:
            start_dt = datetime.combine(current_day, item.start_time)
            end_dt = datetime.combine(current_day, item.end_time)
            event_map.setdefault(current_day, []).append(
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
                    'task_id': None,
                }
            )
        current_day += timedelta(days=1)

    for academic_event in academic_events:
        event_map.setdefault(academic_event.event_date, []).append(build_academic_calendar_event(academic_event, now))

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
        snapshot['timeline_events'] = [
            build_timeline_event(event)
            for event in day_events
            if not event.get('is_all_day')
            and event['end'].hour * 60 + event['end'].minute > TIMELINE_START_HOUR * 60
            and event['start'].hour * 60 + event['start'].minute < TIMELINE_END_HOUR * 60
        ]
        snapshot['all_day_events'] = [event for event in day_events if event.get('is_all_day')]
        snapshot['is_selected'] = current_day == selected_date
        week_days.append(snapshot)
    return week_days


def get_timeline_visual_type(event):
    if event['type'] == 'schedule':
        lesson_type = (event.get('meta') or '').lower()
        if any(token in lesson_type for token in ('практ', 'лаб', 'practice', 'laboratory')):
            return 'practice'
        return 'lecture'
    if event['type'] == 'task':
        return 'deadline'
    if event['type'] == 'academic':
        return 'exam'
    if event['type'] in {'schedule-change', 'override'}:
        return 'change'
    return 'lecture'


def build_timeline_event(event):
    timeline_start = TIMELINE_START_HOUR * 60
    timeline_end = TIMELINE_END_HOUR * 60
    timeline_duration = timeline_end - timeline_start
    event_start = event['start'].hour * 60 + event['start'].minute
    event_end = event['end'].hour * 60 + event['end'].minute
    visible_start = max(event_start, timeline_start)
    visible_end = min(max(event_end, visible_start + 30), timeline_end)
    return {
        **event,
        'timeline_top': round(((visible_start - timeline_start) / timeline_duration) * 100, 4),
        'timeline_height': round(max(((visible_end - visible_start) / timeline_duration) * 100, 4.5), 4),
        'visual_type': get_timeline_visual_type(event),
    }


def summarize_selected_day(selected_events):
    task_count = sum(1 for event in selected_events if event['type'] == 'task')
    schedule_count = sum(1 for event in selected_events if event['type'] in {'schedule', 'schedule-change'})
    academic_count = sum(1 for event in selected_events if event['type'] == 'academic')
    schedule_change_count = sum(1 for event in selected_events if event['type'] == 'schedule-change')
    override_count = sum(1 for event in selected_events if event['type'] == 'override')
    timed_events = [event for event in selected_events if not event.get('is_all_day')]
    first_event_time = timed_events[0]['start'].strftime('%H:%M') if timed_events else None
    last_event_time = timed_events[-1]['end'].strftime('%H:%M') if timed_events else None
    load_minutes = sum(
        max(0, int((event['end'] - event['start']).total_seconds() // 60))
        for event in timed_events
    )
    weight = get_event_weight(selected_events)
    return {
        'event_count': len(selected_events),
        'task_count': task_count,
        'schedule_count': schedule_count,
        'academic_count': academic_count,
        'schedule_change_count': schedule_change_count,
        'override_count': override_count,
        'has_override': override_count > 0,
        'first_event_time': first_event_time,
        'last_event_time': last_event_time,
        'load_duration_label': (
            f'{load_minutes // 60}ч {load_minutes % 60:02d}м'
            if load_minutes >= 60
            else f'{load_minutes} мин'
        ),
        'load_label': (
            'Высокая нагрузка' if weight >= 7
            else 'Средняя нагрузка' if weight >= 3
            else 'Особый день' if override_count
            else 'Легкий день' if selected_events
            else 'Свободный день'
        ),
    }


def build_upcoming_events(event_map, selected_date: date, limit: int = 6):
    upcoming = []
    now = current_time()
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


def build_filtered_upcoming_events(event_map, selected_date: date, event_types: set[str], limit: int = 5):
    upcoming = []
    now = current_time()
    for day in sorted(day for day in event_map.keys() if day >= selected_date):
        for event in event_map[day]:
            if event['type'] not in event_types or event['end'] < now:
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


def format_week_period_label(selected_date: date):
    week_start = selected_date - timedelta(days=selected_date.weekday())
    week_end = week_start + timedelta(days=6)
    if week_start.year != week_end.year:
        return (
            f'{week_start.day} {MONTH_NAMES_RU_GENITIVE[week_start.month]} {week_start.year} — '
            f'{week_end.day} {MONTH_NAMES_RU_GENITIVE[week_end.month]} {week_end.year}'
        )
    if week_start.month != week_end.month:
        return (
            f'{week_start.day} {MONTH_NAMES_RU_GENITIVE[week_start.month]} — '
            f'{week_end.day} {MONTH_NAMES_RU_GENITIVE[week_end.month]} {week_end.year}'
        )
    return f'{week_start.day} — {week_end.day} {MONTH_NAMES_RU_GENITIVE[week_end.month]} {week_end.year}'


def build_calendar_page_context(
    user: User,
    db: Session,
    year: int | None = None,
    month: int | None = None,
    selected_date_raw: str | None = None,
    view_mode: str = 'week',
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
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    week_days = build_week_days(month_context['event_map'], selected_date)
    upcoming_events = build_upcoming_events(month_context['event_map'], selected_date)
    upcoming_deadlines = build_filtered_upcoming_events(month_context['event_map'], selected_date, {'task'}, limit=4)
    upcoming_session_events = build_filtered_upcoming_events(month_context['event_map'], selected_date, {'academic'})
    upcoming_schedule_changes = build_filtered_upcoming_events(
        month_context['event_map'],
        selected_date,
        {'override', 'schedule-change'},
    )
    selected_summary = summarize_selected_day(selected_events)
    navigation = build_period_navigation(selected_date, 'week')
    selected_day_override = next((event for event in selected_events if event['type'] == 'override'), None)
    month_events = [
        event
        for day, events in month_context['event_map'].items()
        if day.year == safe_year and day.month == safe_month
        for event in events
    ]
    previous_calendar_year, previous_calendar_month = shift_calendar_period(safe_year, safe_month, -1)
    next_calendar_year, next_calendar_month = shift_calendar_period(safe_year, safe_month, 1)
    today = current_date()

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
        'selected_month_name': MONTH_NAMES_RU_GENITIVE[selected_date.month],
        'week_period_label': format_week_period_label(selected_date),
        'timeline_hours': [f'{hour:02d}:00' for hour in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR)],
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
        'previous_calendar_year': previous_calendar_year,
        'previous_calendar_month': previous_calendar_month,
        'next_calendar_year': next_calendar_year,
        'next_calendar_month': next_calendar_month,
        'today_year': today.year,
        'today_month': today.month,
        'today_iso': today.isoformat(),
        'period_label': navigation['period_label'],
        'period_kind': navigation['period_kind'],
        'month_task_count': sum(1 for event in month_events if event['type'] == 'task'),
        'month_schedule_count': sum(1 for event in month_events if event['type'] in {'schedule', 'schedule-change'}),
        'month_academic_count': sum(1 for event in month_events if event['type'] == 'academic'),
        'month_schedule_change_count': sum(1 for event in month_events if event['type'] == 'schedule-change'),
        'month_override_count': sum(1 for event in month_events if event['type'] == 'override'),
        'weekly_schedule_count': weekly_schedule_count,
        'last_study_day': getattr(user, 'last_study_day', None),
        'subjects': subjects,
        'session_event_types': SESSION_EVENT_TYPES,
        'calendar_event_type_options': CALENDAR_EVENT_TYPE_OPTIONS,
        'schedule_terms': schedule_terms,
        'view_mode': safe_view_mode,
        'week_days': week_days,
        'selected_summary': selected_summary,
        'selected_day_override': selected_day_override,
        'upcoming_events': upcoming_events,
        'upcoming_deadlines': upcoming_deadlines,
        'upcoming_session_events': upcoming_session_events,
        'upcoming_schedule_changes': upcoming_schedule_changes,
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
                f'DTSTAMP:{datetime.now().astimezone().strftime("%Y%m%dT%H%M%SZ")}',
                f'DTSTART;TZID={APP_TIMEZONE}:{format_ics_datetime(event["start"])}',
                f'DTEND;TZID={APP_TIMEZONE}:{format_ics_datetime(event["end"])}',
                f'SUMMARY:{escape_ics_text(summary)}',
                f'DESCRIPTION:{escape_ics_text(" | ".join(part for part in description_parts if part))}',
                f'LOCATION:{escape_ics_text(", ".join(part for part in location_parts if part))}',
                'END:VEVENT',
            ])

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines).encode('utf-8')
