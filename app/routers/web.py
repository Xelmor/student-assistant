import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta
import calendar
import os
import random
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Subject, Task, ScheduleItem, Note
from ..auth import hash_password, verify_password, get_current_user
from ..utils import WEEKDAYS, calculate_task_score

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
APP_TIMEZONE = 'Europe/Moscow'
MONTH_NAMES_RU = {
    1: 'январь',
    2: 'февраль',
    3: 'март',
    4: 'апрель',
    5: 'май',
    6: 'июнь',
    7: 'июль',
    8: 'август',
    9: 'сентябрь',
    10: 'октябрь',
    11: 'ноябрь',
    12: 'декабрь',
}
SCHEDULE_UNIT_OPTIONS = {
    'pair': {
        'label': 'Пары',
        'singular': 'пара',
        'plural': 'пары',
        'plural_genitive': 'пар',
    },
    'lesson': {
        'label': 'Уроки',
        'singular': 'урок',
        'plural': 'уроки',
        'plural_genitive': 'уроков',
    },
    'class': {
        'label': 'Занятия',
        'singular': 'занятие',
        'plural': 'занятия',
        'plural_genitive': 'занятий',
    },
}
SCHEDULE_TIME_PRESETS = {
    'free': {
        'label': 'Свободный',
        'slots': [],
    },
    'university': {
        'label': 'ВУЗ',
        'slots': [
            {'key': 'u1', 'label': '1 пара: 09:00 - 10:30', 'start': '09:00', 'end': '10:30'},
            {'key': 'u2', 'label': '2 пара: 10:40 - 12:10', 'start': '10:40', 'end': '12:10'},
            {'key': 'u3', 'label': '3 пара: 12:40 - 14:10', 'start': '12:40', 'end': '14:10'},
            {'key': 'u4', 'label': '4 пара: 14:20 - 15:50', 'start': '14:20', 'end': '15:50'},
            {'key': 'u5', 'label': '5 пара: 16:20 - 17:50', 'start': '16:20', 'end': '17:50'},
            {'key': 'u6', 'label': '6 пара: 18:00 - 19:30', 'start': '18:00', 'end': '19:30'},
        ],
    },
    'school': {
        'label': 'Школа',
        'slots': [
            {'key': 's1', 'label': '1 урок: 08:00 - 08:40', 'start': '08:00', 'end': '08:40'},
            {'key': 's2', 'label': '2 урок: 08:50 - 09:30', 'start': '08:50', 'end': '09:30'},
            {'key': 's3', 'label': '3 урок: 09:45 - 10:25', 'start': '09:45', 'end': '10:25'},
            {'key': 's4', 'label': '4 урок: 10:40 - 11:20', 'start': '10:40', 'end': '11:20'},
            {'key': 's5', 'label': '5 урок: 11:30 - 12:10', 'start': '11:30', 'end': '12:10'},
        ],
    },
}
MOTIVATIONAL_QUOTES = [
    'Маленький шаг сегодня делает большую разницу к концу семестра.',
    'Не нужно делать все идеально, нужно просто двигаться вперед.',
    'Одна закрытая задача сегодня лучше десяти отложенных на потом.',
    'Стабильность в учебе сильнее, чем редкие рывки в последний момент.',
    'Каждая пара и каждая заметка сейчас работают на твой будущий результат.',
    'Даже короткая учебная сессия сегодня приближает тебя к цели.',
    'Спокойный ритм и ясный план всегда выигрывают у хаоса.',
]


def serialize_datetime(value):
    if not value:
        return None
    return value.isoformat()


def serialize_time(value):
    if not value:
        return None
    return value.strftime('%H:%M:%S')


def parse_datetime_value(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def parse_time_value(value):
    if not value:
        return None
    return datetime.strptime(value, '%H:%M:%S').time()


def normalize_calendar_period(year: int | None, month: int | None):
    today = datetime.now().date()
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


def build_calendar_event_map(user: User, db: Session, year: int, month: int):
    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    visible_dates = [day for week in month_matrix for day in week]
    visible_start = visible_dates[0]
    visible_end = visible_dates[-1]
    today = datetime.now().date()

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
                    'is_overdue': (not task.is_completed) and task.deadline < datetime.now(),
                    'description': task.description or '',
                    'room': None,
                }
            )

    current_date = visible_start
    while current_date <= visible_end:
        matching_items = [
            item for item in schedule_items
            if item.weekday == current_date.weekday()
        ]
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
            day_events = event_map.get(day, [])
            schedule_events = [event for event in day_events if event['type'] == 'schedule']
            task_events = [event for event in day_events if event['type'] == 'task']
            first_schedule_start = schedule_events[0]['start'].strftime('%H:%M') if schedule_events else None
            last_schedule_end = schedule_events[-1]['end'].strftime('%H:%M') if schedule_events else None
            first_schedule_index = 1 if schedule_events else None
            last_schedule_index = len(schedule_events) if schedule_events else None
            week_cells.append(
                {
                    'date': day,
                    'day': day.day,
                    'in_month': day.month == month,
                    'is_today': day == today,
                    'event_count': len(day_events),
                    'has_task': bool(task_events),
                    'has_schedule': bool(schedule_events),
                    'has_overdue': any(event['is_overdue'] for event in day_events),
                    'task_count': len(task_events),
                    'first_schedule_start': first_schedule_start,
                    'last_schedule_end': last_schedule_end,
                    'first_schedule_index': first_schedule_index,
                    'last_schedule_index': last_schedule_index,
                }
            )
        weeks.append(week_cells)

    return {
        'weeks': weeks,
        'event_map': event_map,
        'visible_start': visible_start,
        'visible_end': visible_end,
    }


def build_calendar_page_context(user: User, db: Session, year: int | None = None, month: int | None = None, selected_date_raw: str | None = None):
    safe_year, safe_month = normalize_calendar_period(year, month)
    month_context = build_calendar_event_map(user, db, safe_year, safe_month)
    schedule_terms = get_schedule_terms(user)
    selected_date = iso_date_or_none(selected_date_raw)
    if selected_date is None or selected_date not in month_context['event_map']:
        today = datetime.now().date()
        if today in month_context['event_map'] and today.month == safe_month and today.year == safe_year:
            selected_date = today
        else:
            selected_date = next(iter(month_context['event_map'].keys()))

    previous_year, previous_month = shift_calendar_period(safe_year, safe_month, -1)
    next_year, next_month = shift_calendar_period(safe_year, safe_month, 1)
    selected_events = month_context['event_map'].get(selected_date, [])
    weekly_schedule_count = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).count()

    return {
        'calendar_year': safe_year,
        'calendar_month': safe_month,
        'calendar_label': f"{MONTH_NAMES_RU[safe_month]} {safe_year}",
        'calendar_weeks': month_context['weeks'],
        'selected_date': selected_date,
        'selected_events': selected_events,
        'previous_year': previous_year,
        'previous_month': previous_month,
        'next_year': next_year,
        'next_month': next_month,
        'month_task_count': sum(1 for events in month_context['event_map'].values() for event in events if event['type'] == 'task'),
        'month_schedule_count': sum(1 for events in month_context['event_map'].values() for event in events if event['type'] == 'schedule'),
        'weekly_schedule_count': weekly_schedule_count,
        'schedule_terms': schedule_terms,
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
                summary = f"Дедлайн: {summary}"

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


def build_user_export_payload(user: User, db: Session):
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.id.asc()).all()
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.id.asc()).all()
    schedule_items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(ScheduleItem.id.asc()).all()
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.id.asc()).all()

    return {
        'version': 1,
        'exported_at': datetime.utcnow().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
            'group_name': user.group_name,
            'course': user.course,
            'schedule_unit': user.schedule_unit,
        },
        'data': {
            'subjects': [
                {
                    'id': subject.id,
                    'name': subject.name,
                    'teacher': subject.teacher,
                    'room': subject.room,
                    'color': subject.color,
                    'notes': subject.notes,
                }
                for subject in subjects
            ],
            'tasks': [
                {
                    'id': task.id,
                    'subject_id': task.subject_id,
                    'title': task.title,
                    'description': task.description,
                    'deadline': serialize_datetime(task.deadline),
                    'priority': task.priority,
                    'difficulty': task.difficulty,
                    'is_completed': task.is_completed,
                    'created_at': serialize_datetime(task.created_at),
                }
                for task in tasks
            ],
            'schedule_items': [
                {
                    'id': item.id,
                    'subject_id': item.subject_id,
                    'weekday': item.weekday,
                    'start_time': serialize_time(item.start_time),
                    'end_time': serialize_time(item.end_time),
                    'lesson_type': item.lesson_type,
                    'room': item.room,
                }
                for item in schedule_items
            ],
            'notes': [
                {
                    'id': note.id,
                    'subject_id': note.subject_id,
                    'title': note.title,
                    'content': note.content,
                    'link': note.link,
                    'created_at': serialize_datetime(note.created_at),
                }
                for note in notes
            ],
        },
    }


def build_csv_export_archive(payload):
    archive_buffer = io.BytesIO()

    csv_specs = {
        'subjects.csv': (
            ['id', 'name', 'teacher', 'room', 'color', 'notes'],
            payload['data']['subjects'],
        ),
        'tasks.csv': (
            ['id', 'subject_id', 'title', 'description', 'deadline', 'priority', 'difficulty', 'is_completed', 'created_at'],
            payload['data']['tasks'],
        ),
        'schedule_items.csv': (
            ['id', 'subject_id', 'weekday', 'start_time', 'end_time', 'lesson_type', 'room'],
            payload['data']['schedule_items'],
        ),
        'notes.csv': (
            ['id', 'subject_id', 'title', 'content', 'link', 'created_at'],
            payload['data']['notes'],
        ),
    }

    with zipfile.ZipFile(archive_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('export_meta.json', json.dumps({
            'version': payload['version'],
            'exported_at': payload['exported_at'],
            'user': payload['user'],
        }, ensure_ascii=False, indent=2))

        for filename, (fieldnames, rows) in csv_specs.items():
            text_buffer = io.StringIO()
            writer = csv.DictWriter(text_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field) for field in fieldnames})
            archive.writestr(filename, text_buffer.getvalue().encode('utf-8-sig'))

    archive_buffer.seek(0)
    return archive_buffer


def build_download_headers(filename: str):
    return {
        'Content-Disposition': f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote_plus(filename)}',
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    }


def import_user_export_payload(user: User, payload, import_mode: str, db: Session):
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ValueError('В файле нет блока data с данными для импорта.')

    user_payload = payload.get('user', {})
    if isinstance(user_payload, dict):
        imported_schedule_unit = user_payload.get('schedule_unit')
        if imported_schedule_unit in SCHEDULE_UNIT_OPTIONS:
            user.schedule_unit = imported_schedule_unit

    subjects_payload = data.get('subjects', [])
    tasks_payload = data.get('tasks', [])
    schedule_payload = data.get('schedule_items', [])
    notes_payload = data.get('notes', [])

    for collection, label in [
        (subjects_payload, 'subjects'),
        (tasks_payload, 'tasks'),
        (schedule_payload, 'schedule_items'),
        (notes_payload, 'notes'),
    ]:
        if not isinstance(collection, list):
            raise ValueError(f'Поле {label} должно быть списком.')

    subject_id_map = {}

    if import_mode == 'replace':
        db.query(Note).filter(Note.user_id == user.id).delete(synchronize_session=False)
        db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).delete(synchronize_session=False)
        db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
        db.query(Subject).filter(Subject.user_id == user.id).delete(synchronize_session=False)
        db.flush()

    for subject_payload in subjects_payload:
        subject = Subject(
            user_id=user.id,
            name=(subject_payload.get('name') or '').strip() or 'Без названия',
            teacher=subject_payload.get('teacher') or None,
            room=subject_payload.get('room') or None,
            color=subject_payload.get('color') or '#0d6efd',
            notes=subject_payload.get('notes') or None,
        )
        db.add(subject)
        db.flush()
        original_subject_id = subject_payload.get('id')
        if original_subject_id is not None:
            subject_id_map[original_subject_id] = subject.id

    for task_payload in tasks_payload:
        task = Task(
            user_id=user.id,
            subject_id=subject_id_map.get(task_payload.get('subject_id')),
            title=(task_payload.get('title') or '').strip() or 'Без названия',
            description=task_payload.get('description') or None,
            deadline=parse_datetime_value(task_payload.get('deadline')),
            priority=task_payload.get('priority') or 'medium',
            difficulty=task_payload.get('difficulty') or 'medium',
            is_completed=bool(task_payload.get('is_completed', False)),
            created_at=parse_datetime_value(task_payload.get('created_at')) or datetime.utcnow(),
        )
        db.add(task)

    for schedule_payload_item in schedule_payload:
        mapped_subject_id = subject_id_map.get(schedule_payload_item.get('subject_id'))
        if not mapped_subject_id:
            continue

        schedule_item = ScheduleItem(
            user_id=user.id,
            subject_id=mapped_subject_id,
            weekday=int(schedule_payload_item.get('weekday', 0)),
            start_time=parse_time_value(schedule_payload_item.get('start_time')) or datetime.strptime('09:00:00', '%H:%M:%S').time(),
            end_time=parse_time_value(schedule_payload_item.get('end_time')) or datetime.strptime('10:00:00', '%H:%M:%S').time(),
            lesson_type=schedule_payload_item.get('lesson_type') or None,
            room=schedule_payload_item.get('room') or None,
        )
        db.add(schedule_item)

    for note_payload in notes_payload:
        note = Note(
            user_id=user.id,
            subject_id=subject_id_map.get(note_payload.get('subject_id')),
            title=(note_payload.get('title') or '').strip() or 'Без названия',
            content=note_payload.get('content') or None,
            link=note_payload.get('link') or None,
            created_at=parse_datetime_value(note_payload.get('created_at')) or datetime.utcnow(),
        )
        db.add(note)


def profile_message_redirect(*, success: str | None = None, error: str | None = None):
    params = []
    if success:
        params.append(f'data_success={quote_plus(success)}')
    if error:
        params.append(f'data_error={quote_plus(error)}')
    location = '/profile'
    if params:
        location = f"{location}?{'&'.join(params)}"
    return RedirectResponse(location, status_code=302)


def require_user(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        return None
    return user


def get_schedule_terms(user: User | None):
    schedule_unit = getattr(user, 'schedule_unit', None) or 'class'
    return SCHEDULE_UNIT_OPTIONS.get(schedule_unit, SCHEDULE_UNIT_OPTIONS['class'])


def parse_schedule_time(value: str):
    normalized_value = value.strip()
    if len(normalized_value) == 4 and normalized_value[1] == ':':
        normalized_value = f'0{normalized_value}'
    return datetime.strptime(normalized_value, '%H:%M').time()


def is_valid_schedule_time_range(start_time, end_time):
    return start_time < end_time


def is_local_private_data_enabled(request: Request) -> bool:
    enabled = os.getenv('ALLOW_LOCAL_PRIVATE_DATA', 'false').lower() == 'true'
    client_host = request.client.host if request.client else ''
    return enabled and client_host in {'127.0.0.1', '::1', 'localhost'}


@router.get('/', response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse('/dashboard', status_code=302)
    return templates.TemplateResponse(request, 'index.html', {})


@router.get('/register', response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, 'register.html', {'error': None})


@router.post('/register', response_class=HTMLResponse)
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    group_name: str = Form(''),
    course: int | None = Form(None),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'register.html',
            {'error': 'Пользователь с таким логином или email уже существует.'}
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        group_name=group_name or None,
        course=course,
        schedule_unit='class',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session['user_id'] = user.id
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, 'login.html', {'error': None})


@router.post('/login', response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            'login.html',
            {'error': 'Неверный логин или пароль.'}
        )
    request.session['user_id'] = user.id
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/forgot-password', response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        'forgot_password.html',
        {'error': None, 'success': None}
    )


@router.post('/forgot-password', response_class=HTMLResponse)
def forgot_password(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пароли не совпадают.', 'success': None}
        )

    if len(new_password) < 6:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пароль должен быть не короче 6 символов.', 'success': None}
        )

    user = db.query(User).filter(User.username == username, User.email == email).first()
    if not user:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пользователь с таким логином и email не найден.', 'success': None}
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        request,
        'forgot_password.html',
        {'error': None, 'success': 'Пароль обновлен. Теперь можно войти с новым паролем.'}
    )


@router.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/', status_code=302)


@router.get('/profile', response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    data_success = request.query_params.get('data_success')
    data_error = request.query_params.get('data_error')
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    return templates.TemplateResponse(
        request,
        'profile.html',
        {
            'user': user,
            'error': None,
            'success': None,
            'local_private_data_available': is_local_private_data_enabled(request),
            'data_success': data_success,
            'data_error': data_error,
            'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
        }
    )


@router.post('/profile', response_class=HTMLResponse)
def update_profile(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    group_name: str = Form(''),
    course: int | None = Form(None),
    schedule_unit: str = Form('class'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    existing = db.query(User).filter(
        ((User.username == username) | (User.email == email)) & (User.id != user.id)
    ).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'profile.html',
            {
                'user': user,
                'error': 'Пользователь с таким логином или email уже существует.',
                'success': None,
                'local_private_data_available': is_local_private_data_enabled(request),
                'data_success': None,
                'data_error': None,
                'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
            }
        )

    if schedule_unit not in SCHEDULE_UNIT_OPTIONS:
        schedule_unit = 'class'

    user.username = username
    user.email = email
    user.group_name = group_name or None
    user.course = course
    user.schedule_unit = schedule_unit
    db.commit()
    db.refresh(user)
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()

    return templates.TemplateResponse(
        request,
        'profile.html',
        {
            'user': user,
            'error': None,
            'success': 'Профиль обновлен.',
            'local_private_data_available': is_local_private_data_enabled(request),
            'data_success': None,
            'data_error': None,
            'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
        }
    )


@router.get('/data/export/{export_format}')
@router.get('/data/export/{export_format}/')
def export_data(export_format: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    payload = build_user_export_payload(user, db)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
    safe_username = ''.join(character for character in user.username if character.isalnum() or character in {'-', '_'}) or 'student'

    if export_format == 'json':
        json_buffer = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
        filename = f'{safe_username}_student_assistant_backup_{timestamp}.json'
        return StreamingResponse(
            json_buffer,
            media_type='application/octet-stream',
            headers=build_download_headers(filename),
        )

    if export_format == 'csv':
        archive_buffer = build_csv_export_archive(payload)
        filename = f'{safe_username}_student_assistant_export_{timestamp}.zip'
        return StreamingResponse(
            archive_buffer,
            media_type='application/zip',
            headers=build_download_headers(filename),
        )

    return profile_message_redirect(error='Неподдерживаемый формат экспорта.')


@router.post('/data/import')
async def import_data(
    request: Request,
    import_file: UploadFile = File(...),
    import_mode: str = Form('merge'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if import_mode not in {'merge', 'replace'}:
        return profile_message_redirect(error='Неизвестный режим импорта.')

    if not import_file.filename:
        return profile_message_redirect(error='Выбери JSON-файл для импорта.')

    if not import_file.filename.lower().endswith('.json'):
        return profile_message_redirect(error='Сейчас импорт поддерживается только из JSON-файла.')

    file_bytes = await import_file.read()
    if not file_bytes:
        return profile_message_redirect(error='Файл пустой.')

    try:
        payload = json.loads(file_bytes.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return profile_message_redirect(error='Не удалось прочитать JSON-файл. Проверь формат.')

    try:
        import_user_export_payload(user, payload, import_mode, db)
        db.commit()
    except ValueError as error:
        db.rollback()
        return profile_message_redirect(error=str(error))
    except Exception:
        db.rollback()
        return profile_message_redirect(error='Импорт не удался из-за ошибки в данных.')

    return profile_message_redirect(success='Данные успешно импортированы.')


@router.get('/local-profile', response_class=HTMLResponse)
def local_profile_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if not is_local_private_data_enabled(request):
        return RedirectResponse('/dashboard', status_code=302)

    return templates.TemplateResponse(
        request,
        'local_profile.html',
        {
            'user': user,
        }
    )


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = datetime.now()
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    pending_tasks = [t for t in tasks if not t.is_completed]
    completed_tasks = [t for t in tasks if t.is_completed]
    overdue_tasks = [t for t in pending_tasks if t.deadline and t.deadline < now]
    urgent_tasks = sorted(pending_tasks, key=calculate_task_score, reverse=True)[:5]

    today_weekday = now.weekday()
    today_schedule = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user.id,
        ScheduleItem.weekday == today_weekday,
    ).order_by(ScheduleItem.start_time.asc()).all()
    now_time = now.time()
    active_schedule_item = None
    next_schedule_item = None
    active_schedule_remaining_seconds = 0

    for item in today_schedule:
        if item.start_time <= now_time < item.end_time:
            active_schedule_item = item
            lesson_end = datetime.combine(now.date(), item.end_time)
            active_schedule_remaining_seconds = max(0, int((lesson_end - now).total_seconds()))
            break
        if now_time < item.start_time and next_schedule_item is None:
            next_schedule_item = item

    schedule_terms = get_schedule_terms(user)

    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(now.year, now.month)
    calendar_days = []
    for week in month_matrix:
        for date_value in week:
            calendar_days.append({
                'day': date_value.day,
                'in_month': date_value.month == now.month,
                'is_today': date_value == now.date(),
            })

    context = {
        'user': user,
        'local_private_data_available': is_local_private_data_enabled(request),
        'subjects_count': db.query(Subject).filter(Subject.user_id == user.id).count(),
        'pending_count': len(pending_tasks),
        'completed_count': len(completed_tasks),
        'overdue_count': len(overdue_tasks),
        'urgent_tasks': urgent_tasks,
        'today_schedule': today_schedule,
        'active_schedule_item': active_schedule_item,
        'next_schedule_item': next_schedule_item,
        'active_schedule_remaining_seconds': active_schedule_remaining_seconds,
        'weekdays': WEEKDAYS,
        'now': now,
        'calendar_days': calendar_days,
        'motivation_quote': random.choice(MOTIVATIONAL_QUOTES),
        'schedule_terms': schedule_terms,
    }
    return templates.TemplateResponse(request, 'dashboard.html', context)


@router.get('/calendar', response_class=HTMLResponse)
def calendar_page(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    selected: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    context = build_calendar_page_context(user, db, year, month, selected)
    context.update({'user': user, 'weekdays': WEEKDAYS})
    return templates.TemplateResponse(request, 'calendar.html', context)


@router.get('/calendar/export/ics')
def export_calendar_ics(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    safe_year, safe_month = normalize_calendar_period(year, month)
    calendar_bytes = build_ics_calendar(user, db, safe_year, safe_month)
    filename = f'{user.username}_calendar_{safe_year}-{safe_month:02d}.ics'
    return StreamingResponse(
        io.BytesIO(calendar_bytes),
        media_type='text/calendar; charset=utf-8',
        headers=build_download_headers(filename),
    )


@router.get('/subjects', response_class=HTMLResponse)
def subjects_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(request, 'subjects.html', {'user': user, 'subjects': subjects})


@router.post('/subjects/add')
def add_subject(
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subject = Subject(
        user_id=user.id,
        name=name,
        teacher=teacher or None,
        room=room or None,
        color=color,
        notes=notes or None,
    )
    db.add(subject)
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.post('/subjects/edit/{subject_id}')
def edit_subject(
    subject_id: int,
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if not subject:
        return RedirectResponse('/subjects', status_code=302)

    subject.name = name
    subject.teacher = teacher or None
    subject.room = room or None
    subject.color = color
    subject.notes = notes or None
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.get('/subjects/delete/{subject_id}')
def delete_subject(subject_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if subject:
        db.delete(subject)
        db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.is_completed.asc(), Task.deadline.asc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'tasks.html',
        {
            'user': user,
            'tasks': tasks,
            'subjects': subjects,
            'now': datetime.now(),
        }
    )


@router.post('/tasks/add')
def add_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    deadline_value = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task = Task(
        user_id=user.id,
        subject_id=subject_id if subject_id else None,
        title=title,
        description=description or None,
        deadline=deadline_value,
        priority=priority,
        difficulty=difficulty,
    )
    db.add(task)
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.post('/tasks/edit/{task_id}')
def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        return RedirectResponse('/tasks', status_code=302)

    if subject_id:
        subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/tasks', status_code=302)

    task.title = title
    task.description = description or None
    task.subject_id = subject_id if subject_id else None
    task.deadline = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task.priority = priority
    task.difficulty = difficulty
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/toggle/{task_id}')
def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        task.is_completed = not task.is_completed
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/delete/{task_id}')
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/schedule', response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(
        ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()
    ).all()

    grouped = {i: [] for i in range(7)}
    for item in items:
        grouped[item.weekday].append(item)

    return templates.TemplateResponse(
        request,
        'schedule.html',
        {
            'user': user,
            'subjects': subjects,
            'grouped': grouped,
            'weekdays': WEEKDAYS,
            'schedule_time_presets': SCHEDULE_TIME_PRESETS,
        }
    )


@router.post('/schedule/add')
async def add_schedule_items(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    form = await request.form()
    subject_id_values = form.getlist('subject_id')
    weekday_values = form.getlist('weekday')
    start_time_values = form.getlist('start_time')
    end_time_values = form.getlist('end_time')
    lesson_type_values = form.getlist('lesson_type')
    room_values = form.getlist('room')

    total_rows = len(subject_id_values)

    for i in range(total_rows):
        current_subject_id = subject_id_values[i] if i < len(subject_id_values) else ''
        current_weekday = weekday_values[i] if i < len(weekday_values) else ''
        current_start_time = start_time_values[i].strip() if i < len(start_time_values) else ''
        current_end_time = end_time_values[i].strip() if i < len(end_time_values) else ''
        current_lesson_type = lesson_type_values[i].strip() if i < len(lesson_type_values) else ''
        current_room = room_values[i].strip() if i < len(room_values) else ''

        if not current_subject_id or current_weekday == '' or not current_start_time or not current_end_time:
            continue

        subject = db.query(Subject).filter(
            Subject.id == int(current_subject_id),
            Subject.user_id == user.id
        ).first()

        if not subject:
            continue

        parsed_start_time = parse_schedule_time(current_start_time)
        parsed_end_time = parse_schedule_time(current_end_time)
        if not is_valid_schedule_time_range(parsed_start_time, parsed_end_time):
            continue

        item = ScheduleItem(
            user_id=user.id,
            subject_id=int(current_subject_id),
            weekday=int(current_weekday),
            start_time=parsed_start_time,
            end_time=parsed_end_time,
            lesson_type=current_lesson_type or None,
            room=current_room or None,
        )
        db.add(item)

    db.commit()
    return RedirectResponse('/schedule', status_code=302)


@router.post('/schedule/edit/{item_id}')
def edit_schedule_item(
    item_id: int,
    request: Request,
    subject_id: int = Form(...),
    weekday: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    lesson_type: str = Form(''),
    room: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    item = db.query(ScheduleItem).filter(
        ScheduleItem.id == item_id,
        ScheduleItem.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse('/schedule', status_code=302)

    subject = db.query(Subject).filter(
        Subject.id == subject_id,
        Subject.user_id == user.id
    ).first()
    if not subject:
        return RedirectResponse('/schedule', status_code=302)

    item.subject_id = subject_id
    item.weekday = weekday
    parsed_start_time = parse_schedule_time(start_time)
    parsed_end_time = parse_schedule_time(end_time)
    if not is_valid_schedule_time_range(parsed_start_time, parsed_end_time):
        return RedirectResponse('/schedule', status_code=302)

    item.start_time = parsed_start_time
    item.end_time = parsed_end_time
    item.lesson_type = lesson_type.strip() or None
    item.room = room.strip() or None
    db.commit()

    return RedirectResponse('/schedule', status_code=302)


@router.get('/schedule/delete/{item_id}')
def delete_schedule_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    item = db.query(ScheduleItem).filter(ScheduleItem.id == item_id, ScheduleItem.user_id == user.id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse('/schedule', status_code=302)


@router.get('/notes', response_class=HTMLResponse)
def notes_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'notes.html',
        {
            'user': user,
            'notes': notes,
            'subjects': subjects,
        }
    )


@router.post('/notes/add')
def add_note(
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note = Note(
        user_id=user.id,
        subject_id=subject_id_value,
        title=title,
        content=content or None,
        link=link or None,
    )
    db.add(note)
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.post('/notes/edit/{note_id}')
@router.post('/notes/edit/{note_id}/')
def edit_note(
    note_id: int,
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if not note:
        return RedirectResponse('/notes', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note.title = title
    note.content = content or None
    note.link = link or None
    note.subject_id = subject_id_value
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/edit/{note_id}')
@router.get('/notes/edit/{note_id}/')
def edit_note_fallback(
    note_id: int,
    request: Request,
    title: str | None = Query(None),
    content: str = Query(''),
    link: str = Query(''),
    subject_id: str = Query(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if title is None:
        return RedirectResponse('/notes', status_code=302)

    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if not note:
        return RedirectResponse('/notes', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note.title = title
    note.content = content or None
    note.link = link or None
    note.subject_id = subject_id_value
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/delete/{note_id}')
def delete_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if note:
        db.delete(note)
        db.commit()
    return RedirectResponse('/notes', status_code=302)
