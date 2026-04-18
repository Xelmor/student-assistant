import secrets
from datetime import datetime
from hmac import compare_digest
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.security import get_current_user
from ..models import User


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / 'templates'))

LEVEL_LABELS = {
    'high': 'Высокий',
    'medium': 'Средний',
    'low': 'Низкий',
}

DIFFICULTY_LABELS = {
    'high': 'Высокая',
    'medium': 'Средняя',
    'low': 'Низкая',
}


def csrf_input(request: Request) -> Markup:
    token = request.session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        request.session['csrf_token'] = token
    return Markup(f'<input type="hidden" name="csrf_token" value="{escape(token)}">')


templates.env.globals['csrf_input'] = csrf_input


def level_label(value: str | None) -> str:
    return LEVEL_LABELS.get((value or '').lower(), value or '')


templates.env.globals['level_label'] = level_label


def difficulty_label(value: str | None) -> str:
    return DIFFICULTY_LABELS.get((value or '').lower(), value or '')


templates.env.globals['difficulty_label'] = difficulty_label

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
    'Каждая пара и каждое занятие сейчас работают на твой будущий результат.',
    'Даже короткая учебная сессия сегодня приближает тебя к цели.',
    'Спокойный ритм и ясный план всегда выигрывают у хаоса.',
]


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


async def validate_csrf(request: Request, csrf_token: str | None = Form(None)):
    session_token = request.session.get('csrf_token')
    if not session_token:
        request.session['csrf_token'] = secrets.token_urlsafe(32)
        session_token = request.session['csrf_token']

    if not csrf_token or not compare_digest(csrf_token, session_token):
        raise HTTPException(status_code=403, detail='Invalid CSRF token.')


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
    client_host = request.client.host if request.client else ''
    return settings.allow_local_private_data and client_host in {'127.0.0.1', '::1', 'localhost'}
