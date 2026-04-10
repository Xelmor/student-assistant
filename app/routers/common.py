import os
from datetime import datetime
from urllib.parse import quote_plus

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..models import User

templates = Jinja2Templates(directory='app/templates')

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
