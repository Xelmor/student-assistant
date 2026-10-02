from __future__ import annotations

import json
import logging
import secrets
import string
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import current_date as app_current_date, current_time
from .telegram_digest import digest_local_datetime
from ..core.validation import normalize_bounded_text
from ..models import AcademicEvent, ScheduleItem, Subject, Task, User
from .task_completion import complete_task
from .telegram_now import build_now_message
from .telegram_today import build_today_summary, build_today_schedule
from .telegram_task_parser import parse_task, conversational_intent
from . import telegram_task_draft as task_draft
from . import telegram_task_actions as task_actions
from . import telegram_task_views as task_views
from . import telegram_class_reminders as class_reminders
from . import telegram_notes
from . import telegram_evening_digest as evening_digest
from . import telegram_weekly_digest as weekly_digest
from .calendar_service import effective_schedule_for_day
from .telegram_state import consume_limit, state_row, utcnow
from .task_schedule_links import get_task_anchor_datetime
from .telegram_digest import (
    build_morning_digest_message,
    digest_send_time,
    resolve_digest_timezone_name,
)
from .telegram_notifications import (
    VALID_DEADLINE_REMINDER_HOURS,
    deadline_reminder_hours,
)


logger = logging.getLogger(__name__)

TELEGRAM_API_ORIGIN = 'https://api.telegram.org'
DEFAULT_SITE_URL = 'https://student-assistant-beby.onrender.com'
LINK_CODE_ALPHABET = ''.join(
    character
    for character in string.ascii_uppercase + string.digits
    if character not in {'0', 'O', '1', 'I', 'L'}
)
MAX_TASKS = 7
MAX_WEEK_DEADLINES = 5
MESSAGE_DIVIDER = '━━━━━━━━━━━━━━'
PRIORITY_LABELS = {'high': 'высокий', 'medium': 'средний', 'low': 'низкий'}
PRIORITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}
PRIORITY_MARKERS = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
PRIORITY_ALIASES = {
    'высокий': 'high',
    'high': 'high',
    'средний': 'medium',
    'medium': 'medium',
    'низкий': 'low',
    'low': 'low',
}
# Public command menu only; dispatch below also accepts the hidden commands.
BOT_COMMANDS = [
    {'command': 'start', 'description': 'Главное меню'},
    {'command': 'today', 'description': 'Сегодня'},
    {'command': 'tomorrow', 'description': 'Завтра'},
    {'command': 'week', 'description': 'Неделя'},
    {'command': 'tasks', 'description': 'Задачи'},
    {'command': 'add_task', 'description': 'Добавить задачу'},
]
INTERNAL_BOT_COMMANDS = frozenset({
    'now', 'help', 'link', 'notifications', 'digest', 'digest_on', 'digest_off',
    'digest_test', 'done', 'cancel', 'site', 'unlink',
})
WEEKDAY_SHORT_NAMES = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
MONTH_NAMES_GENITIVE = {
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


class TelegramAPIError(RuntimeError):
    def __init__(self, message='Telegram request failed', *, category='temporary', status=None, retry_after=None):
        self.category = category
        self.status = status
        self.retry_after = retry_after
        self.retryable = category in {'temporary', 'network', 'rate_limit'}
        # Never retain API descriptions, URLs, payloads or chained exceptions.
        super().__init__(f'Telegram: {category}' + (f' (HTTP {status})' if status else ''))


@dataclass(frozen=True)
class TelegramReply:
    chat_id: int
    text: str
    parse_mode: str = 'HTML'
    reply_markup: dict | None = None
    callback_query_id: str | None = None
    chat_action: str | None = None


@dataclass(frozen=True)
class AddedTask:
    task: Task
    deadline_warning: bool = False
    subject_warning: bool = False


@dataclass
class AddTaskDialog:
    user_id: int
    chat_id: int
    step: str
    title: str | None = None
    deadline: datetime | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    priority: str = 'medium'
    subject_warning: bool = False
    generation: str = field(default_factory=lambda: secrets.token_hex(4))
    natural: bool = False
    editing: bool = False
    warning: str | None = None
    subject_candidates: list[int] = field(default_factory=list)
    subject_title: str | None = None
    edit_task_id: int | None = None
    task_revision: str | None = None
    original_deadline: str | None = None
    awaiting_phrase: bool = False
    time_explicit: bool = True


ADD_TASK_WAITING_TITLE = 'add_task_waiting_title'
ADD_TASK_WAITING_DEADLINE = 'add_task_waiting_deadline'
ADD_TASK_WAITING_CUSTOM_DEADLINE = 'add_task_waiting_custom_deadline'
ADD_TASK_WAITING_SUBJECT = 'add_task_waiting_subject'
ADD_TASK_WAITING_CUSTOM_SUBJECT = 'add_task_waiting_custom_subject'
ADD_TASK_WAITING_PRIORITY = 'add_task_waiting_priority'
ADD_TASK_CONFIRM = 'add_task_confirm'
ADD_TASK_QUICK_CONFIRM = 'add_task_quick_confirm'
DIALOG_STEPS = [ADD_TASK_WAITING_TITLE, ADD_TASK_WAITING_DEADLINE, ADD_TASK_WAITING_CUSTOM_DEADLINE,
                ADD_TASK_WAITING_SUBJECT, ADD_TASK_WAITING_CUSTOM_SUBJECT, ADD_TASK_WAITING_PRIORITY,
                ADD_TASK_CONFIRM, ADD_TASK_QUICK_CONFIRM, *task_actions.RESCHEDULE_STEPS]
_DIALOG_CONTEXT = ContextVar('telegram_dialog_context', default=None)
_USER_DATE = ContextVar('telegram_user_date', default=None)


def current_date():
    return _USER_DATE.get() or app_current_date()


def clear_telegram_dialog_states() -> None:
    """Compatibility hook; durable state belongs to its database, not this process."""


def _get_add_task_dialog(telegram_user_id: int) -> AddTaskDialog | None:
    context = _DIALOG_CONTEXT.get()
    return context.get('dialog') if context else None


def _set_add_task_dialog(telegram_user_id: int, dialog: AddTaskDialog) -> AddTaskDialog:
    _DIALOG_CONTEXT.get()['dialog'] = dialog
    return dialog


def _clear_add_task_dialog(telegram_user_id: int) -> bool:
    context = _DIALOG_CONTEXT.get()
    return context.pop('dialog', None) is not None if context else False


def _commit(db):
    if db.info.get('telegram_atomic'):
        db.flush()
    else:
        db.commit()


def _html(value: object) -> str:
    return escape(str(value), quote=False)


def _site_url() -> str:
    return settings.public_base_url or DEFAULT_SITE_URL


def _callback_button(text: str, callback_data: str) -> dict:
    return {'text': text, 'callback_data': callback_data}


def _url_button(text: str, url: str | None = None) -> dict:
    return {'text': text, 'url': url or _site_url()}


def _keyboard(*rows: list[dict]) -> dict:
    return {'inline_keyboard': list(rows)}


def _site_help_keyboard() -> dict:
    return _keyboard(
        [_callback_button('🔗 Подключить Telegram', 'connect')],
        [_url_button('🌐 Открыть сайт')],
    )


def _main_keyboard() -> dict:
    return _keyboard(
        [_callback_button('📍 Сейчас', 'now')],
        [_callback_button('📅 Сегодня', 'today'), _callback_button('📆 Завтра', 'tomorrow')],
        [_callback_button('🗓 Неделя', 'week'), _callback_button('📌 Задачи', 'tasks')],
        [_callback_button('➕ Добавить задачу', 'add_task_start')],
        [_callback_button('📝 Заметка', 'note_start')],
        [_callback_button('⚙️ Настройки', 'settings'), _callback_button('🌐 Сайт', 'site')],
    )


def _help_keyboard() -> dict:
    return _main_keyboard()


def _settings_keyboard() -> dict:
    return _keyboard(
        [_callback_button('🌅 Утренняя сводка', 'digest')],
        [_callback_button('⏰ Напоминания о дедлайнах', 'deadline_settings')],
        [_callback_button('🔗 Статус подключения', 'connection_status')],
        [_callback_button('🚪 Отключить Telegram', 'unlink')],
        [_callback_button('🎓 Пары', 'class_settings')],
        [_callback_button('🌙 Вечерняя сводка', 'evening_settings')],
        [_callback_button('📊 Недельный обзор', 'weekly_settings')],
        [_callback_button('← Назад', 'start')],
    )


def _settings_back_button() -> list[dict]:
    return [_callback_button('← Назад', 'settings')]


def _now_keyboard() -> dict:
    return _keyboard(
        [_callback_button('📅 Сегодня', 'today'), _callback_button('📌 Задачи', 'tasks')],
        [_callback_button('🔄 Обновить', 'now')],
    )


def _today_keyboard() -> dict:
    return _keyboard(
        [_callback_button('📍 Сейчас', 'now'), _callback_button('🗓 Расписание', 'today_schedule')],
        [_callback_button('📌 Все задачи', 'tasks'), _callback_button('➕ Добавить задачу', 'add_task_start')],
        [_callback_button('🔄 Обновить', 'today')],
    )


def _today_schedule_keyboard() -> dict:
    return _keyboard(
        [_callback_button('← Сегодня', 'today')],
        [_callback_button('📍 Сейчас', 'now')],
    )


def _tomorrow_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📅 Сегодня', 'today'),
            _callback_button('📌 Задачи', 'tasks'),
        ],
        [
            _callback_button('🗓 Неделя', 'week'),
            _callback_button('🌐 Сайт', 'site'),
        ],
    )


def _week_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📅 Сегодня', 'today'),
            _callback_button('📌 Задачи', 'tasks'),
        ],
        [_callback_button('🌐 Сайт', 'site')],
    )


def _tasks_keyboard(tasks: list[Task] | None = None) -> dict:
    rows = [
        [_callback_button(f'✅ Закрыть {index}', f'done_task:{task.id}')]
        for index, task in enumerate(tasks or [], start=1)
    ]
    rows.extend(
        [
            [
                _callback_button('📅 Сегодня', 'today'),
                _callback_button('📆 Завтра', 'tomorrow'),
            ],
            [
                _callback_button('➕ Добавить задачу', 'add_task_start'),
                _callback_button('🌐 Сайт', 'site'),
            ],
        ]
    )
    return _keyboard(*rows)


def _done_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📌 Задачи', 'tasks'),
            _callback_button('📅 Сегодня', 'today'),
        ],
        [_callback_button('🌐 Сайт', 'site')],
    )


def _done_error_keyboard() -> dict:
    return _keyboard([_callback_button('📌 Задачи', 'tasks')])


def _add_task_navigation_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📌 Задачи', 'tasks'),
            _callback_button('🌐 Сайт', 'site'),
        ],
    )


def _add_task_success_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📌 Задачи', 'tasks'),
            _callback_button('➕ Добавить ещё', 'add_task_start'),
        ],
        [_callback_button('🌐 Сайт', 'site')],
    )


def _add_task_cancel_keyboard() -> dict:
    return _keyboard([_callback_button('❌ Отменить', 'add_task_cancel')])


def _add_task_deadline_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('Сегодня', 'add_task_deadline_today'),
            _callback_button('Завтра', 'add_task_deadline_tomorrow'),
        ],
        [
            _callback_button('Без даты', 'add_task_deadline_none'),
            _callback_button('Ввести дату', 'add_task_deadline_custom'),
        ],
        [_callback_button('❌ Отменить', 'add_task_cancel')],
    )


def _add_task_custom_deadline_keyboard() -> dict:
    return _keyboard(
        [_callback_button('Без даты', 'add_task_deadline_none')],
        [_callback_button('❌ Отменить', 'add_task_cancel')],
    )


def _add_task_subject_keyboard(subjects: list[Subject]) -> dict:
    rows = [
        [_callback_button(subject.name, f'add_task_subject:{subject.id}')]
        for subject in subjects[:8]
    ]
    rows.extend(
        [
            [
                _callback_button('Без предмета', 'add_task_subject_none'),
                _callback_button('Ввести предмет', 'add_task_subject_custom'),
            ],
            [_callback_button('❌ Отменить', 'add_task_cancel')],
        ]
    )
    return _keyboard(*rows)


def _add_task_priority_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('🔴 Высокий', 'add_task_priority_high'),
            _callback_button('🟡 Средний', 'add_task_priority_medium'),
        ],
        [_callback_button('🟢 Низкий', 'add_task_priority_low')],
        [_callback_button('❌ Отменить', 'add_task_cancel')],
    )


def _add_task_confirm_keyboard() -> dict:
    return _keyboard(
        [_callback_button('✅ Создать задачу', 'add_task_confirm_create')],
        [
            _callback_button('Начать заново', 'add_task_restart'),
            _callback_button('❌ Отменить', 'add_task_cancel'),
        ],
    )


def _add_task_existing_dialog_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('Начать заново', 'add_task_restart'),
            _callback_button('Продолжить', 'add_task_continue'),
        ],
        [_callback_button('❌ Отменить', 'add_task_cancel')],
    )


def _quick_task_offer_keyboard() -> dict:
    return _keyboard(
        [_callback_button('✅ Да, добавить', 'add_task_quick_create')],
        [
            _callback_button('Настроить', 'add_task_quick_customize'),
            _callback_button('❌ Отменить', 'add_task_cancel'),
        ],
    )


def _unlink_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('✅ Да, отключить', 'unlink_confirm'),
            _callback_button('Отмена', 'unlink_cancel'),
        ],
    )


def _digest_keyboard(user: User) -> dict:
    toggle = (
        _callback_button('⛔ Выключить', 'digest_off')
        if user.telegram_morning_digest_enabled
        else _callback_button('✅ Включить', 'digest_on')
    )
    return _keyboard(
        [toggle, _callback_button('🧪 Тестовая сводка', 'digest_test')],
        [_url_button('⚙️ Настроить на сайте', f'{_site_url()}/profile#profile-telegram')],
        _settings_back_button(),
    )


def _digest_summary_keyboard() -> dict:
    return _keyboard(
        [
            _callback_button('📅 Сегодня', 'today'),
            _callback_button('📌 Задачи', 'tasks'),
        ],
        [_url_button('🌐 Открыть сайт')],
    )


def _notifications_keyboard(user: User) -> dict:
    digest_label = (
        '🌅 Выключить сводку'
        if user.telegram_morning_digest_enabled
        else '🌅 Включить сводку'
    )
    deadline_label = (
        '⏰ Выключить дедлайны'
        if user.telegram_deadline_reminders_enabled
        else '⏰ Включить дедлайны'
    )
    selected_hours = deadline_reminder_hours(user)
    hour_buttons = [
        _callback_button(
            f'{"✓ " if selected_hours == hours else ""}{hours} ч',
            f'deadline_hours:{hours}',
        )
        for hours in VALID_DEADLINE_REMINDER_HOURS
    ]
    return _keyboard(
        [
            _callback_button(digest_label, 'digest_toggle'),
            _callback_button('🧪 Тест сводки', 'digest_test'),
        ],
        [_callback_button(deadline_label, 'deadline_toggle')],
        hour_buttons,
        [_url_button('🌐 Настройки на сайте', f'{_site_url()}/profile#profile-telegram')],
        _settings_back_button(),
    )


def _deadline_keyboard(user: User) -> dict:
    # Reuse the existing notification controls and callback handlers.
    rows = _notifications_keyboard(user)['inline_keyboard']
    return _keyboard(rows[1], rows[2], _settings_back_button())


def generate_link_code(db: Session, user: User) -> str:
    expires_at = current_time() + timedelta(minutes=settings.telegram_link_code_ttl_minutes)

    for _ in range(20):
        code = ''.join(secrets.choice(LINK_CODE_ALPHABET) for _ in range(6))
        existing = db.query(User.id).filter(User.telegram_link_code == code).first()
        if existing:
            continue

        try:
            changed = db.query(User).filter(
                User.id == user.id, User.telegram_user_id.is_(None),
            ).update({User.telegram_link_code: code, User.telegram_link_code_expires_at: expires_at},
                     synchronize_session=False)
            if changed != 1:
                db.rollback()
                raise RuntimeError('Telegram уже подключён.')
            _commit(db)
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(user)
        return code

    raise RuntimeError('Не удалось создать код подключения. Попробуйте ещё раз.')


def clear_telegram_link(user: User) -> None:
    user.telegram_user_id = None
    user.telegram_chat_id = None
    user.telegram_username = None
    user.telegram_linked_at = None
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    user.telegram_morning_digest_enabled = False
    user.telegram_deadline_reminders_enabled = False


def unlink_telegram_user(db: Session, user: User) -> None:
    clear_telegram_link(user)
    _commit(db)


def get_active_link_code(user: User) -> str | None:
    if not user.telegram_link_code or not user.telegram_link_code_expires_at:
        return None
    if user.telegram_link_code_expires_at <= current_time():
        return None
    return user.telegram_link_code


def _telegram_user(db: Session, telegram_user_id: int) -> User | None:
    return db.query(User).filter(User.telegram_user_id == telegram_user_id).first()


def _display_name(user: User) -> str:
    return user.display_name or user.username


def build_not_linked_message() -> str:
    return (
        '🔗 <b>Аккаунт не подключён</b>\n\n'
        'Сначала подключи Telegram через профиль на сайте.'
    )


def build_help_message() -> str:
    return (
        '<b>Что умеет Student Assistant:</b>\n'
        '📅 Сегодня\n'
        '📆 Завтра\n'
        '🗓 Неделя\n'
        '📌 Задачи\n'
        '➕ Добавить задачу\n'
        '⚙️ Настройки'
    )


def _format_schedule(items: list[ScheduleItem]) -> list[str]:
    rows = []
    for item in items:
        row = (
            f"🕘 {item.start_time.strftime('%H:%M')}–{item.end_time.strftime('%H:%M')} "
            f"— <b>{_html(item.subject.name)}</b>"
        )
        details = []
        if item.lesson_type:
            details.append(_html(item.lesson_type))
        if item.room:
            details.append(f'Аудитория: {_html(item.room)}')
        if details:
            row += '\n   ' + ' · '.join(details)
        rows.append(row)
    return rows


def _format_today_tasks(tasks: list[Task], today) -> list[str]:
    rows = []
    for index, task in enumerate(tasks, start=1):
        anchor = get_task_anchor_datetime(task)
        deadline = _format_deadline(anchor, today=today)
        priority = PRIORITY_LABELS.get(task.priority or 'medium', 'средний')
        marker = PRIORITY_MARKERS.get(task.priority or 'medium', '⚪')
        rows.append(
            f'{index}. <b>{_html(task.title)}</b>\n'
            f'   Дедлайн: {deadline}\n'
            f'   Приоритет: {marker} {priority}'
        )
    return rows


def _format_events(events: list[AcademicEvent]) -> list[str]:
    rows = []
    for event in events:
        time_label = event.start_time.strftime('%H:%M') if event.start_time else 'весь день'
        details = [_html(event.title)]
        if event.room:
            details.append(f'ауд. {_html(event.room)}')
        rows.append(f"{time_label} — {' · '.join(details)}")
    return rows


def _format_deadline(anchor: datetime | None, *, today=None) -> str:
    if anchor is None:
        return 'без даты'

    reference_date = today or current_date()
    if anchor.date() == reference_date:
        return f"сегодня {anchor.strftime('%H:%M')}"
    if anchor.date() == reference_date + timedelta(days=1):
        return f"завтра {anchor.strftime('%H:%M')}"
    return (
        f'{anchor.day} {MONTH_NAMES_GENITIVE[anchor.month]} '
        f'{anchor.strftime("%H:%M")}'
    )


def _day_plan(
    db: Session,
    user: User,
    target_date: date,
) -> tuple[list[ScheduleItem], list[Task], list[AcademicEvent]]:
    schedule_items = effective_schedule_for_day(db, user, target_date)
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.is_completed.is_(False))
        .all()
    )
    tasks = [
        task
        for task in tasks
        if (
            (task.deadline is not None and task.deadline.date() == target_date)
            or task.scheduled_for_date == target_date
        )
    ]
    tasks.sort(key=lambda task: get_task_anchor_datetime(task) or datetime.max)
    events = (
        db.query(AcademicEvent)
        .filter(
            AcademicEvent.user_id == user.id,
            AcademicEvent.event_date == target_date,
        )
        .order_by(AcademicEvent.start_time.asc())
        .all()
    )
    return schedule_items, tasks, events


def _build_day_message(
    db: Session,
    user: User,
    *,
    target_date: date,
    heading: str,
    subtitle: str,
    empty_message: str,
    footer: str,
) -> str:
    schedule_items, tasks, events = _day_plan(db, user, target_date)

    if not schedule_items and not tasks and not events:
        return (
            f'📅 <b>{heading}</b> <i>{subtitle}</i>\n\n'
            f'{MESSAGE_DIVIDER}\n\n'
            f'{empty_message}'
        )

    sections = [
        f'📅 <b>{heading}</b> <i>{subtitle}</i>',
        MESSAGE_DIVIDER,
    ]
    if schedule_items:
        sections.append('<b>Пары</b>\n' + '\n\n'.join(_format_schedule(schedule_items)))
    if tasks:
        sections.append(
            '<b>Задачи</b>\n'
            + '\n\n'.join(_format_today_tasks(tasks, current_date()))
        )
    if events:
        sections.append('<b>События</b>\n' + '\n'.join(_format_events(events)))
    sections.append(MESSAGE_DIVIDER)
    sections.append(f'<i>{footer}</i>')
    return '\n\n'.join(sections)


def build_today_message(db: Session, user: User) -> str:
    return build_today_summary(db, user, now_utc=digest_local_datetime(user))


def build_tomorrow_message(db: Session, user: User) -> str:
    return _build_day_message(
        db,
        user,
        target_date=current_date() + timedelta(days=1),
        heading='Завтра',
        subtitle='План на следующий день',
        empty_message=(
            'На завтра ничего не запланировано ✅\n\n'
            'Можно заранее подготовиться или спокойно освободить день.'
        ),
        footer='Лучше подготовиться заранее 🎓',
    )


def _active_tasks_for_user(
    db: Session,
    user: User,
    *,
    limit: int | None = MAX_TASKS,
) -> list[Task]:
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.is_completed.is_(False))
        .all()
    )
    tasks.sort(
        key=lambda task: (
            get_task_anchor_datetime(task) is None,
            get_task_anchor_datetime(task) or datetime.max,
            PRIORITY_ORDER.get(task.priority or 'medium', 1),
            task.created_at or datetime.min,
        )
    )
    return tasks[:limit] if limit is not None else tasks


def _remember_task_list(db, user, tasks):
    data = {'ids': [task.id for task in tasks]}
    if db.info.get('telegram_atomic'):
        # A failed /tasks reply must not replace the numbering the user actually saw.
        db.info['telegram_task_snapshot'] = {'user_id': user.id, **data}
    else:
        snapshot = state_row(db, f'tasks:{user.id}')
        snapshot.data = data
        snapshot.expires_at = utcnow() + timedelta(minutes=30)
        _commit(db)


def build_tasks_message(db: Session, user: User, tasks: list[Task] | None = None) -> str:
    if tasks is None:
        tasks = _active_tasks_for_user(db, user)
    _remember_task_list(db, user, tasks)
    if not tasks:
        return (
            '📌 <b>Ближайшие задачи</b> <i>Активные дедлайны</i>\n\n'
            f'{MESSAGE_DIVIDER}\n\n'
            'Активных задач пока нет ✅\n\n'
            'Когда появятся новые учебные дела, я покажу их здесь.'
        )

    rows = []
    for index, task in enumerate(tasks, start=1):
        anchor = get_task_anchor_datetime(task)
        deadline = _format_deadline(anchor)
        priority = PRIORITY_LABELS.get(task.priority or 'medium', 'средний')
        marker = PRIORITY_MARKERS.get(task.priority or 'medium', '⚪')
        details = []
        if task.subject:
            details.append(f'   Предмет: {_html(task.subject.name)}')
        details.extend(
            [
                f'   Дедлайн: {deadline}',
                f'   Приоритет: {marker} {priority}',
            ]
        )
        rows.append(f'{index}. <b>{_html(task.title)}</b>\n' + '\n'.join(details))
    return (
        '📌 <b>Ближайшие задачи</b> <i>То, что важно не забыть</i>\n\n'
        f'{MESSAGE_DIVIDER}\n\n'
        + '\n\n'.join(rows)
        + f'\n\n{MESSAGE_DIVIDER}\n\n'
        '<i>Показываю только ближайшие активные задачи.</i>'
    )


def _pluralize_count(value: int, forms: tuple[str, str, str]) -> str:
    remainder_100 = value % 100
    remainder_10 = value % 10
    if 11 <= remainder_100 <= 14:
        form = forms[2]
    elif remainder_10 == 1:
        form = forms[0]
    elif remainder_10 in {2, 3, 4}:
        form = forms[1]
    else:
        form = forms[2]
    return f'{value} {form}'


def _short_date(value: date) -> str:
    return f'{value.day} {MONTH_NAMES_GENITIVE[value.month]}'


def build_week_message(db: Session, user: User) -> str:
    start_date = current_date()
    end_date = start_date + timedelta(days=6)
    schedule_items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.user_id == user.id)
        .all()
    )
    tasks = _active_tasks_for_user(db, user, limit=None)
    dated_tasks = [
        task
        for task in tasks
        if (
            (anchor := get_task_anchor_datetime(task)) is not None
            and start_date <= anchor.date() <= end_date
        )
    ]
    events = (
        db.query(AcademicEvent)
        .filter(
            AcademicEvent.user_id == user.id,
            AcademicEvent.event_date >= start_date,
            AcademicEvent.event_date <= end_date,
        )
        .all()
    )

    has_schedule = any(effective_schedule_for_day(db, user, start_date + timedelta(days=i)) for i in range(7))
    if not has_schedule and not dated_tasks and not events:
        return (
            '🗓 <b>Ближайшая неделя</b> <i>Обзор на 7 дней</i>\n\n'
            f'{MESSAGE_DIVIDER}\n\n'
            'На ближайшую неделю пока ничего не запланировано ✅'
        )

    task_counts: dict[date, int] = {}
    for task in dated_tasks:
        anchor = get_task_anchor_datetime(task)
        if anchor is not None:
            task_counts[anchor.date()] = task_counts.get(anchor.date(), 0) + 1
    event_counts: dict[date, int] = {}
    for event in events:
        event_counts[event.event_date] = event_counts.get(event.event_date, 0) + 1
    schedule_counts: dict[int, int] = {}
    for item in schedule_items:
        schedule_counts[item.weekday] = schedule_counts.get(item.weekday, 0) + 1

    day_rows = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        details = []
        lesson_count = len(effective_schedule_for_day(db, user, day))
        task_count = task_counts.get(day, 0)
        event_count = event_counts.get(day, 0)
        if lesson_count:
            details.append(_pluralize_count(lesson_count, ('пара', 'пары', 'пар')))
        if task_count:
            details.append(_pluralize_count(task_count, ('задача', 'задачи', 'задач')))
        if event_count:
            details.append(
                _pluralize_count(event_count, ('событие', 'события', 'событий'))
            )
        summary = ', '.join(details) if details else 'свободно'
        day_rows.append(
            f'{WEEKDAY_SHORT_NAMES[day.weekday()]}, {_short_date(day)} — {summary}'
        )

    dated_tasks.sort(
        key=lambda task: (
            get_task_anchor_datetime(task) or datetime.max,
            PRIORITY_ORDER.get(task.priority or 'medium', 1),
            task.created_at or datetime.min,
        )
    )
    deadline_rows = []
    for index, task in enumerate(dated_tasks[:MAX_WEEK_DEADLINES], start=1):
        anchor = get_task_anchor_datetime(task)
        if anchor is None:
            continue
        marker = PRIORITY_MARKERS.get(task.priority or 'medium', '⚪')
        priority = PRIORITY_LABELS.get(task.priority or 'medium', 'средний')
        deadline_rows.append(
            f'{index}. <b>{_html(task.title)}</b>\n'
            f'   Дата: {_short_date(anchor.date())}\n'
            f'   Приоритет: {marker} {priority}'
        )

    sections = [
        '🗓 <b>Ближайшая неделя</b> <i>Обзор на 7 дней</i>',
        MESSAGE_DIVIDER,
        '<b>Кратко по дням</b>\n\n' + '\n'.join(day_rows),
    ]
    if deadline_rows:
        sections.extend(
            [
                MESSAGE_DIVIDER,
                '<b>Ближайшие дедлайны</b>\n\n' + '\n\n'.join(deadline_rows),
            ]
        )
    sections.extend([MESSAGE_DIVIDER, '<i>Неделя под контролем 🚀</i>'])
    return '\n\n'.join(sections)


def build_done_help_message() -> str:
    return (
        '✅ <b>Закрытие задачи</b>\n\n'
        'Сначала открой нужную карточку задачи:\n\n'
        '<code>/tasks</code>\n\n'
        'Затем отправь:\n\n'
        '<code>/done 1</code>\n\n'
        'Бот выполнит задачу из последней показанной карточки.'
    )


def _complete_task(db: Session, task: Task) -> None:
    complete_task(db, task)
    task_actions.mark_changed(db, task)
    _commit(db)


def _resolve_done_task(
    db: Session,
    user: User,
    argument: str,
    *,
    task_id: int | None = None,
) -> tuple[str, Task | None]:
    if task_id is not None:
        task = (
            db.query(Task)
            .filter(Task.id == task_id, Task.user_id == user.id)
            .with_for_update().first()
        )
    else:
        normalized = argument.strip()
        if not normalized.isdigit():
            return 'missing', None
        number = int(normalized)
        snapshot = state_row(db, f'tasks:{user.id}')
        ids = snapshot.data.get('ids', []) if snapshot.expires_at > utcnow() else []
        if not 1 <= number <= len(ids):
            return 'missing', None
        task = db.query(Task).filter(Task.id == ids[number - 1], Task.user_id == user.id).with_for_update().first()

    if task is None:
        return 'missing', None
    if task.is_completed:
        return 'completed', task

    _complete_task(db, task)
    return 'success', task


def build_done_result_message(status: str, task: Task | None) -> str:
    if status == 'success' and task is not None:
        return (
            '✅ <b>Задача выполнена</b>\n\n'
            f'📌 <b>{_html(task.title)}</b>\n\n'
            'Отлично! Она больше не будет показываться в активных задачах.'
        )
    if status == 'completed':
        return (
            '✅ <b>Эта задача уже выполнена</b>\n\n'
            'Можешь открыть актуальный список активных задач.'
        )
    return (
        '⚠️ <b>Задача не найдена</b>\n\n'
        'Проверь номер задачи в списке:\n\n'
        '<code>/tasks</code>'
    )


def build_add_task_title_message() -> str:
    return (
        '📝 <b>Новая задача</b>\n\n'
        'Напиши название задачи одним сообщением.\n\n'
        'Пример: <code>Сделать практику по Python</code>'
    )


def build_add_task_deadline_message() -> str:
    return (
        '📅 <b>Когда дедлайн?</b>\n\n'
        'Выбери вариант или введи свою дату.'
    )


def build_add_task_custom_deadline_message() -> str:
    return (
        '✍️ <b>Введи дедлайн</b>\n\n'
        'Например:\n'
        '<code>завтра 18:00</code>\n'
        '<code>2026-06-15 23:59</code>\n'
        '<code>15.06.2026</code>'
    )


def build_add_task_subject_message() -> str:
    return (
        '📚 <b>К какому предмету относится задача?</b>\n\n'
        'Выбери предмет, оставь задачу без предмета или введи название вручную.'
    )


def build_add_task_custom_subject_message() -> str:
    return (
        '✍️ <b>Введи название предмета</b>\n\n'
        'Я попробую найти его среди твоих предметов на сайте.'
    )


def build_add_task_priority_message() -> str:
    return '⚡ <b>Выбери приоритет</b>'


def build_add_task_confirmation_message(dialog: AddTaskDialog) -> str:
    deadline = _format_deadline(dialog.deadline) if dialog.deadline else 'без даты'
    subject = _html(dialog.subject_name or 'без предмета')
    priority = PRIORITY_LABELS.get(dialog.priority, 'средний')
    marker = PRIORITY_MARKERS.get(dialog.priority, '🟡')
    sections = [
        '📝 <b>Проверь задачу</b>',
        (
            f'📌 <b>{_html(dialog.title or "")}</b>\n'
            f'Дедлайн: {deadline}\n'
            f'Предмет: {subject}\n'
            f'Приоритет: {marker} {priority}'
        ),
    ]
    if dialog.subject_warning:
        sections.append('⚠️ Предмет не найден, задача будет добавлена без привязки.')
    return '\n\n'.join(sections)


def build_quick_task_offer_message(title: str) -> str:
    return (
        '📝 <b>Добавить это как задачу?</b>\n\n'
        f'<code>{_html(title)}</code>'
    )


def _normalize_subject_name(value: str) -> str:
    return ' '.join(value.split()).casefold()


def _find_user_subject(db: Session, user: User, name: str) -> Subject | None:
    normalized_name = _normalize_subject_name(name)
    if not normalized_name:
        return None

    subjects = db.query(Subject).filter(Subject.user_id == user.id).all()
    return next(
        (
            subject
            for subject in subjects
            if _normalize_subject_name(subject.name) == normalized_name
        ),
        None,
    )


def parse_telegram_deadline(
    value: str | None,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, bool]:
    normalized = ' '.join((value or '').strip().split())
    if not normalized:
        return None, True

    reference = now or current_time()
    lowered = normalized.casefold()
    relative_parts = lowered.split()
    if relative_parts and relative_parts[0] in {'сегодня', 'завтра'}:
        if len(relative_parts) > 2:
            return None, False

        target_date = reference.date()
        if relative_parts[0] == 'завтра':
            target_date += timedelta(days=1)

        hour, minute = 23, 59
        if len(relative_parts) == 2:
            try:
                parsed_time = datetime.strptime(relative_parts[1], '%H:%M')
            except ValueError:
                return None, False
            hour, minute = parsed_time.hour, parsed_time.minute

        return (
            datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hour,
                minute,
            ),
            True,
        )

    for date_format in (
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%d.%m.%Y %H:%M',
        '%d.%m.%Y',
    ):
        try:
            parsed = datetime.strptime(normalized, date_format)
        except ValueError:
            continue
        if date_format in {'%Y-%m-%d', '%d.%m.%Y'}:
            parsed = parsed.replace(hour=23, minute=59)
        return parsed, True

    return None, False


def _parse_add_task_argument(argument: str) -> tuple[str, str, str, str]:
    separator = ',' if ',' in argument else '|'
    parts = [part.strip() for part in argument.split(separator, 3)]
    parts.extend([''] * (4 - len(parts)))
    title = normalize_bounded_text(
        parts[0],
        label='Название задачи',
        max_length=150,
        required=True,
    )
    return title, parts[1], parts[2], parts[3]


def _save_telegram_task(
    db: Session,
    user: User,
    *,
    title: str,
    deadline: datetime | None = None,
    subject_id: int | None = None,
    priority: str = 'medium',
) -> Task:
    task = Task(
        user_id=user.id,
        subject_id=subject_id,
        title=title,
        deadline=deadline,
        priority=priority if priority in PRIORITY_LABELS else 'medium',
        difficulty='medium',
        is_completed=False,
        recurrence_type='none',
    )
    db.add(task)
    try:
        _commit(db)
    except Exception:
        db.rollback()
        raise
    db.refresh(task)
    return task


def create_telegram_task(db: Session, user: User, argument: str) -> AddedTask:
    title, deadline_text, subject_text, priority_text = _parse_add_task_argument(argument)
    deadline, deadline_recognized = parse_telegram_deadline(deadline_text)
    subject = _find_user_subject(db, user, subject_text) if subject_text else None
    priority = PRIORITY_ALIASES.get(priority_text.casefold(), 'medium')

    task = _save_telegram_task(
        db,
        user,
        title=title,
        deadline=deadline,
        subject_id=subject.id if subject else None,
        priority=priority,
    )
    return AddedTask(
        task=task,
        deadline_warning=bool(deadline_text) and not deadline_recognized,
        subject_warning=bool(subject_text) and subject is None,
    )


def build_add_task_success_message(result: AddedTask) -> str:
    task = result.task
    priority = PRIORITY_LABELS.get(task.priority or 'medium', 'средний')
    marker = PRIORITY_MARKERS.get(task.priority or 'medium', '🟡')
    details = []
    if task.deadline:
        details.append(f'Дедлайн: {_format_deadline(task.deadline)}')
    if task.subject:
        details.append(f'Предмет: {_html(task.subject.name)}')
    details.append(f'Приоритет: {marker} {priority}')

    sections = [
        '✅ <b>Задача добавлена</b>',
        f'📌 <b>{_html(task.title)}</b>\n' + '\n'.join(details),
        'Теперь она появится в твоём списке задач на сайте.',
    ]
    warnings = []
    if result.deadline_warning:
        warnings.append('Дедлайн не удалось распознать, задача добавлена без даты.')
    if result.subject_warning:
        warnings.append('Предмет не найден, задача добавлена без привязки.')
    if warnings:
        sections.append('⚠️ ' + '\n⚠️ '.join(warnings))
    return '\n\n'.join(sections)


def _start_add_task_dialog(
    user: User,
    *,
    telegram_user_id: int,
    chat_id: int,
    title: str | None = None,
) -> AddTaskDialog:
    dialog = AddTaskDialog(
        user_id=user.id,
        chat_id=chat_id,
        step=ADD_TASK_WAITING_DEADLINE if title else ADD_TASK_WAITING_TITLE,
        title=title,
        natural=title is None,
        awaiting_phrase=title is None,
    )
    return _set_add_task_dialog(telegram_user_id, dialog)


def _dialog_belongs_to_user(dialog: AddTaskDialog | None, user: User | None) -> bool:
    return dialog is not None and user is not None and dialog.user_id == user.id


def _user_subjects(db: Session, user: User) -> list[Subject]:
    return (
        db.query(Subject)
        .filter(Subject.user_id == user.id)
        .order_by(Subject.name.asc())
        .limit(8)
        .all()
    )


def _render_add_task_dialog_step_base(
    db: Session,
    user: User,
    dialog: AddTaskDialog,
) -> tuple[str, dict]:
    if dialog.step == ADD_TASK_WAITING_TITLE:
        return build_add_task_title_message(), _add_task_cancel_keyboard()
    if dialog.step == ADD_TASK_WAITING_DEADLINE:
        return build_add_task_deadline_message(), _add_task_deadline_keyboard()
    if dialog.step == ADD_TASK_WAITING_CUSTOM_DEADLINE:
        return (
            build_add_task_custom_deadline_message(),
            _add_task_custom_deadline_keyboard(),
        )
    if dialog.step == ADD_TASK_WAITING_SUBJECT:
        return (
            build_add_task_subject_message(),
            _add_task_subject_keyboard(_user_subjects(db, user)),
        )
    if dialog.step == ADD_TASK_WAITING_CUSTOM_SUBJECT:
        return build_add_task_custom_subject_message(), _add_task_cancel_keyboard()
    if dialog.step == ADD_TASK_WAITING_PRIORITY:
        return build_add_task_priority_message(), _add_task_priority_keyboard()
    if dialog.step == ADD_TASK_CONFIRM:
        return build_add_task_confirmation_message(dialog), _add_task_confirm_keyboard()
    if dialog.step == ADD_TASK_QUICK_CONFIRM and dialog.title:
        return build_quick_task_offer_message(dialog.title), _quick_task_offer_keyboard()
    dialog.step = ADD_TASK_WAITING_TITLE
    return build_add_task_title_message(), _add_task_cancel_keyboard()


def _prepare_task_phrase(db, user, *, telegram_user_id, chat_id, argument):
    subjects = [(s.id, s.name) for s in db.query(Subject).filter(Subject.user_id == user.id).all()]
    try:
        parsed = parse_task(argument, now=digest_local_datetime(user), subjects=subjects)
    except ValueError as error:
        return _html(error), _add_task_cancel_keyboard() if _get_add_task_dialog(telegram_user_id) else _help_keyboard()
    if parsed is None:
        return ('Напиши, что нужно сделать, например: «сдать практику завтра в 18». Или выбери раздел в меню.',
                _add_task_cancel_keyboard() if _get_add_task_dialog(telegram_user_id) else _main_keyboard())
    dialog = task_draft.populate_draft(AddTaskDialog(user_id=user.id, chat_id=chat_id, step=ADD_TASK_QUICK_CONFIRM), parsed, subjects)
    _set_add_task_dialog(telegram_user_id, dialog)
    return _render_add_task_dialog_step(db, user, dialog)


def _render_add_task_dialog_step(db, user, dialog):
    if dialog.awaiting_phrase:
        return task_draft.phrase_prompt(), _add_task_cancel_keyboard()
    now = digest_local_datetime(user)
    if dialog.step in task_actions.RESCHEDULE_STEPS:
        return task_actions.render_reschedule(dialog, now.replace(tzinfo=None))
    if dialog.natural and dialog.step in {ADD_TASK_QUICK_CONFIRM, ADD_TASK_CONFIRM}:
        subjects = [(s.id, s.name) for s in db.query(Subject).filter(Subject.user_id == user.id).all()]
        return task_draft.render_draft(dialog, now, subjects)
    text, markup = _render_add_task_dialog_step_base(db, user, dialog)
    return task_draft.edit_prefill(dialog, text, markup, now)


def _advance_dialog_to_subject(
    db: Session,
    user: User,
    dialog: AddTaskDialog,
) -> tuple[str, dict]:
    dialog.step = ADD_TASK_WAITING_SUBJECT
    return _render_add_task_dialog_step(db, user, dialog)


def _create_task_from_dialog(
    db: Session,
    user: User,
    dialog: AddTaskDialog,
) -> Task:
    title = normalize_bounded_text(
        dialog.title,
        label='Название задачи',
        max_length=150,
        required=True,
    )
    subject_id = None
    if dialog.subject_id is not None:
        subject = (
            db.query(Subject)
            .filter(Subject.id == dialog.subject_id, Subject.user_id == user.id)
            .first()
        )
        if subject is not None:
            subject_id = subject.id
    if dialog.edit_task_id is not None:
        task = task_actions.save_edit(db, user, dialog, title=title, subject_id=subject_id)
        _commit(db)
        return task
    return _save_telegram_task(
        db,
        user,
        title=title,
        deadline=dialog.deadline,
        subject_id=subject_id,
        priority=dialog.priority,
    )


def _build_dialog_success_message(task: Task) -> str:
    return (
        '✅ <b>Задача добавлена</b>\n\n'
        f'📌 <b>{_html(task.title)}</b>\n\n'
        'Она появится на сайте и в списке активных задач.'
    )


def _handle_add_task_dialog_action(
    db: Session,
    user: User,
    *,
    telegram_user_id: int,
    chat_id: int,
    action: str,
    argument: str,
) -> tuple[str, dict] | None:
    dialog = _get_add_task_dialog(telegram_user_id)
    if dialog is not None and not _dialog_belongs_to_user(dialog, user):
        _clear_add_task_dialog(telegram_user_id)
        dialog = None

    if action in {'add_task_start', 'add_task_help'}:
        if dialog is not None:
            return (
                '📝 <b>Есть незавершённая задача</b>\n\n'
                'Начать добавление заново или продолжить с текущего шага?',
                _add_task_existing_dialog_keyboard(),
            )
        dialog = _start_add_task_dialog(
            user,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )
        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_restart':
        dialog = _start_add_task_dialog(
            user,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )
        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_continue':
        if dialog is None:
            dialog = _start_add_task_dialog(
                user,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
            )
        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_cancel':
        _clear_add_task_dialog(telegram_user_id)
        return ('Действие отменено.' if dialog and dialog.edit_task_id else 'Добавление задачи отменено.'), _main_keyboard()

    dialog_actions = (
        action.startswith('add_task_deadline_')
        or action.startswith('add_task_subject')
        or action.startswith('add_task_priority_')
        or action
        in {
            'add_task_confirm_create',
            'add_task_quick_create',
            'add_task_quick_customize',
            'add_task_keep',
            'add_task_draft_tomorrow',
        }
    )
    if dialog_actions and dialog is None:
        return (
            '⚠️ <b>Действие устарело</b>\n\n'
            'Начни добавление задачи заново.',
            _keyboard([_callback_button('➕ Добавить задачу', 'add_task_start')]),
        )

    if dialog is None:
        return None

    if dialog.step in task_actions.RESCHEDULE_STEPS:
        try:
            result, finished = task_actions.reschedule_action(db, user, dialog, action, argument, digest_local_datetime(user).replace(tzinfo=None))
        except task_actions.StaleTask:
            _clear_add_task_dialog(telegram_user_id)
            return task_views.stale()
        if finished:
            _clear_add_task_dialog(telegram_user_id)
        else:
            dialog.generation = secrets.token_hex(4)
        return result

    if dialog.awaiting_phrase:
        if action == 'text':
            return _prepare_task_phrase(db, user, telegram_user_id=telegram_user_id, chat_id=chat_id, argument=argument)
        return _render_add_task_dialog_step(db, user, dialog)

    if dialog.natural:
        subjects = [(s.id, s.name) for s in db.query(Subject).filter(Subject.user_id == user.id).all()]
        if task_draft.apply_action(dialog, action, digest_local_datetime(user), subjects):
            return _render_add_task_dialog_step(db, user, dialog)

    if action == 'text':
        if dialog.step == ADD_TASK_WAITING_TITLE:
            try:
                dialog.title = normalize_bounded_text(
                    argument,
                    label='Название задачи',
                    max_length=150,
                    required=True,
                )
            except ValueError as error:
                return (
                    f'⚠️ <b>Проверь название</b>\n\n{_html(error)}',
                    _add_task_cancel_keyboard(),
                )
            dialog.step = ADD_TASK_WAITING_DEADLINE
            return _render_add_task_dialog_step(db, user, dialog)

        if dialog.step == ADD_TASK_WAITING_CUSTOM_DEADLINE:
            deadline, recognized = parse_telegram_deadline(argument, now=digest_local_datetime(user).replace(tzinfo=None))
            if dialog.natural:
                try:
                    parsed = parse_task('Задача ' + argument, now=digest_local_datetime(user))
                    recognized = parsed is not None and parsed.deadline is not None
                    deadline = parsed.deadline if recognized else None
                    if recognized:
                        dialog.time_explicit = parsed.time_explicit
                    dialog.warning = parsed.warning if recognized else None
                except ValueError:
                    recognized = False
            if not recognized:
                return (
                    '⚠️ <b>Не получилось распознать дату</b>\n\n'
                    'Можешь попробовать ещё раз или выбрать «Без даты».',
                    _add_task_custom_deadline_keyboard(),
                )
            dialog.deadline = deadline
            return _advance_dialog_to_subject(db, user, dialog)

        if dialog.step == ADD_TASK_WAITING_CUSTOM_SUBJECT:
            subject = _find_user_subject(db, user, argument)
            dialog.subject_id = subject.id if subject else None
            dialog.subject_name = subject.name if subject else None
            dialog.subject_warning = subject is None
            dialog.step = ADD_TASK_WAITING_PRIORITY
            return _render_add_task_dialog_step(db, user, dialog)

        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_deadline_today':
        dialog.time_explicit = False
        today = current_date()
        dialog.deadline = datetime(today.year, today.month, today.day, 23, 59)
        return _advance_dialog_to_subject(db, user, dialog)
    if action == 'add_task_deadline_tomorrow':
        dialog.time_explicit = False
        tomorrow = current_date() + timedelta(days=1)
        dialog.deadline = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            23,
            59,
        )
        return _advance_dialog_to_subject(db, user, dialog)
    if action == 'add_task_deadline_none':
        dialog.time_explicit = False
        dialog.deadline = None
        return _advance_dialog_to_subject(db, user, dialog)
    if action == 'add_task_deadline_custom':
        dialog.step = ADD_TASK_WAITING_CUSTOM_DEADLINE
        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_subject_none':
        dialog.subject_id = None
        dialog.subject_name = None
        dialog.subject_warning = False
        dialog.step = ADD_TASK_WAITING_PRIORITY
        return _render_add_task_dialog_step(db, user, dialog)
    if action == 'add_task_subject_custom':
        dialog.step = ADD_TASK_WAITING_CUSTOM_SUBJECT
        return _render_add_task_dialog_step(db, user, dialog)
    if action.startswith('add_task_subject:'):
        raw_subject_id = action.partition(':')[2]
        subject = None
        if raw_subject_id.isdigit():
            subject = (
                db.query(Subject)
                .filter(
                    Subject.id == int(raw_subject_id),
                    Subject.user_id == user.id,
                )
                .first()
            )
        dialog.subject_id = subject.id if subject else None
        dialog.subject_name = subject.name if subject else None
        dialog.subject_warning = subject is None
        dialog.step = ADD_TASK_WAITING_PRIORITY
        return _render_add_task_dialog_step(db, user, dialog)

    if action.startswith('add_task_priority_'):
        priority = action.removeprefix('add_task_priority_')
        dialog.priority = priority if priority in PRIORITY_LABELS else 'medium'
        dialog.step = ADD_TASK_CONFIRM
        return _render_add_task_dialog_step(db, user, dialog)

    if action == 'add_task_quick_customize':
        if dialog.natural:
            dialog.generation = secrets.token_hex(4)
            dialog.editing, dialog.warning, dialog.subject_candidates = True, None, []
        dialog.step = ADD_TASK_WAITING_TITLE if dialog.natural else ADD_TASK_WAITING_DEADLINE
        return _render_add_task_dialog_step(db, user, dialog)

    if action in {'add_task_confirm_create', 'add_task_quick_create'}:
        if dialog.step not in {ADD_TASK_CONFIRM, ADD_TASK_QUICK_CONFIRM}:
            return 'Действие устарело. Заверши текущий шаг.', _add_task_cancel_keyboard()
        if dialog.natural and (task_draft.current_warning(dialog, digest_local_datetime(user)) or dialog.subject_candidates):
            return _render_add_task_dialog_step(db, user, dialog)
        try:
            task = _create_task_from_dialog(db, user, dialog)
        except task_actions.StaleTask:
            _clear_add_task_dialog(telegram_user_id)
            return task_views.stale()
        except ValueError as error:
            dialog.warning = str(error)
            return _render_add_task_dialog_step(db, user, dialog)
        except Exception:
            db.rollback()
            logger.error('Telegram task dialog creation failed.')
            return (
                '⚠️ <b>Не удалось добавить задачу</b>\n\n'
                'Произошла ошибка. Попробуй ещё раз позже.',
                _add_task_confirm_keyboard(),
            )
        _clear_add_task_dialog(telegram_user_id)
        if dialog.edit_task_id is not None:
            return task_views.after_update(db, task, '✅ Задача изменена')
        if dialog.natural:
            dialog.subject_name = task.subject.name if task.subject else None
            return task_draft.parsed_success(dialog, digest_local_datetime(user))
        return _build_dialog_success_message(task), _add_task_success_keyboard()

    return None


def _link_account(
    db: Session,
    *,
    code: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_username: str | None,
) -> str:
    normalized_code = code.strip().upper()
    if not normalized_code:
        return 'missing'

    target = db.query(User).filter(User.telegram_link_code == normalized_code).with_for_update().first()
    now = current_time()
    if (
        target is None
        or target.telegram_link_code_expires_at is None
        or target.telegram_link_code_expires_at <= now
    ):
        if target is not None:
            db.query(User).filter(User.id == target.id, User.telegram_link_code == normalized_code,
                                  User.telegram_link_code_expires_at <= now).update(
                {User.telegram_link_code: None}, synchronize_session=False)
            _commit(db)
            db.refresh(target)
        return 'expired'

    linked_user = _telegram_user(db, telegram_user_id)
    if linked_user is not None and linked_user.id != target.id:
        return 'telegram-conflict'
    if target.telegram_user_id is not None and target.telegram_user_id != telegram_user_id:
        return 'account-conflict'

    changed = db.query(User).filter(
        User.id == target.id, User.telegram_link_code == normalized_code,
        User.telegram_link_code_expires_at > now,
        User.telegram_user_id.is_(None),
    ).update({
        User.telegram_user_id: telegram_user_id,
        User.telegram_chat_id: telegram_chat_id,
        User.telegram_username: (telegram_username or '').strip().lstrip('@')[:64] or None,
        User.telegram_linked_at: now,
        User.telegram_link_code: None,
        User.telegram_link_code_expires_at: None,
    }, synchronize_session=False)
    if changed != 1:
        return 'conflict'
    _commit(db)
    db.refresh(target)
    return 'success'


def build_start_unlinked_message() -> str:
    return (
        '👋 <b>Student Assistant</b>\n\n'
        'Привет! Подключи своё пространство с сайта, чтобы продолжить.'
    )


def build_connect_message() -> str:
    return (
        '🔗 <b>Подключить Telegram</b>\n\n'
        '1. Открой свой профиль на сайте.\n'
        '2. Нажми «Подключить Telegram» и получи код.\n'
        '3. Отправь его сюда: <code>/link CODE</code>\n\n'
        'Вместо CODE подставь код из профиля.'
    )


def build_start_linked_message(user: User) -> str:
    return (
        f'👋 <b>Привет, {_html(_display_name(user))}!</b>\n\n'
        'Telegram уже подключён ✅\n'
        'Выбери, что хочешь посмотреть или сделать.'
    )


def build_site_message() -> str:
    return (
        '🌐 <b>Student Assistant</b> <i>Личный кабинет студента</i>\n\n'
        'Управляй задачами, расписанием, предметами, заметками '
        'и дедлайнами в одном месте.'
    )


def build_unknown_command_message() -> str:
    return '🤔 <b>Я пока не понял команду</b>\n\nВыбери действие в меню ниже.'


def build_link_success_message() -> str:
    return (
        '✅ <b>Telegram подключён!</b>\n\n'
        'Теперь ты можешь смотреть расписание и задачи прямо в Telegram.\n\n'
        f'{MESSAGE_DIVIDER}\n\n'
        'Быстрые действия:\n\n'
        '📅 <b>Сегодня</b> — план на день\n'
        '📆 <b>Завтра</b> — следующий учебный день\n'
        '🗓 <b>Неделя</b> — обзор ближайших дней\n'
        '📌 <b>Задачи</b> — ближайшие дедлайны\n'
        '⚙️ <b>Настройки</b> — сводка и напоминания\n'
        '🌐 <b>Сайт</b> — личный кабинет'
    )


def build_digest_settings_message(user: User) -> str:
    status = 'включена ✅' if user.telegram_morning_digest_enabled else 'выключена'
    send_at = digest_send_time(user).strftime('%H:%M')
    timezone_name = resolve_digest_timezone_name(user)
    return (
        '🌅 <b>Утренняя сводка</b>\n\n'
        f'Статус: <b>{status}</b>\n'
        f'Время: <b>{send_at}</b>\n'
        f'Часовой пояс: <code>{_html(timezone_name)}</code>\n\n'
        'В сводке будут пары на сегодня, ближайшая пара и три главные задачи.'
    )


def build_notifications_settings_message(user: User) -> str:
    digest_status = (
        'включена ✅' if user.telegram_morning_digest_enabled else 'выключена'
    )
    deadline_status = (
        'включены ✅' if user.telegram_deadline_reminders_enabled else 'выключены'
    )
    return (
        '⚙️ <b>Telegram-уведомления</b>\n\n'
        f'🌅 Утренняя сводка: <b>{digest_status}</b>\n'
        f'Время: <b>{digest_send_time(user).strftime("%H:%M")}</b>\n\n'
        f'⏰ Дедлайны: <b>{deadline_status}</b>\n'
        f'Напоминать за: <b>{deadline_reminder_hours(user)} ч.</b>\n\n'
        '<i>Настройки применяются только к этому аккаунту Student Assistant.</i>'
    )


def build_link_error_message(status: str) -> str:
    if status == 'missing':
        return (
            '⚠️ <b>Нужен код подключения</b>\n\n'
            'Открой профиль на сайте, создай код и отправь его так:\n\n'
            '<code>/link A7K92Q</code>\n\n'
            'Код действует ограниченное время, поэтому лучше использовать его сразу.'
        )
    if status == 'expired':
        return (
            '⚠️ <b>Код не найден или истёк</b>\n\n'
            'Создай новый код в профиле Student Assistant и отправь его сюда.'
        )
    if status == 'telegram-conflict':
        message = 'Этот Telegram уже подключён к другому аккаунту.'
    elif status == 'account-conflict':
        message = 'Этот аккаунт сайта уже подключён к другому Telegram.'
    else:
        message = 'Аккаунт уже используется. Проверь текущую привязку в профиле.'
    return f'⚠️ <b>Не удалось подключить Telegram</b>\n\n{message}'


def build_unlink_confirm_message() -> str:
    return (
        '⚠️ <b>Отключить Telegram?</b>\n\n'
        'После отключения бот больше не сможет показывать '
        'твои задачи и расписание.'
    )


def _update_linked_identity(
    db: Session,
    user: User | None,
    *,
    chat_id: int,
    sender: dict,
) -> None:
    if user is None or user.telegram_chat_id == chat_id:
        return
    user.telegram_chat_id = chat_id
    username = sender.get('username')
    if isinstance(username, str):
        user.telegram_username = username.strip().lstrip('@')[:64] or None
    _commit(db)


def _handle_telegram_update(db: Session, update: dict) -> TelegramReply | None:
    callback = update.get('callback_query')
    callback_query_id = None
    argument = ''
    if isinstance(callback, dict):
        callback_query_id = callback.get('id')
        action = callback.get('data')
        sender = callback.get('from')
        message = callback.get('message')
        if (
            not isinstance(callback_query_id, str)
            or not isinstance(action, str)
            or not isinstance(sender, dict)
            or not isinstance(message, dict)
        ):
            return None
        chat = message.get('chat')
    else:
        message = update.get('message')
        if not isinstance(message, dict):
            return None
        text = message.get('text')
        chat = message.get('chat')
        sender = message.get('from')
        if not isinstance(text, str):
            return None
        command_line = text.strip()
        if command_line.startswith('/'):
            command_parts = command_line.split(maxsplit=1)
            action = command_parts[0].split('@', 1)[0].lower().lstrip('/')
            argument = command_parts[1].strip() if len(command_parts) > 1 else ''
        else:
            action = 'text'
            argument = command_line

    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    chat_id = chat.get('id')
    telegram_user_id = sender.get('id')
    if (type(chat_id) is not int or type(telegram_user_id) is not int
            or not -(2**63) <= chat_id < 2**63 or not 0 < telegram_user_id < 2**63):
        return None

    if chat.get('type') != 'private':
        return TelegramReply(chat_id=chat_id, text='Открой личный чат с ботом.', callback_query_id=callback_query_id)
    if action == 'start' and argument.startswith('link_'):
        action, argument = 'link', argument[5:]
    if action == 'link' and not consume_limit(db, f'link:{telegram_user_id}', 5, 300):
        return TelegramReply(chat_id=chat_id, text='Слишком много попыток. Подожди 5 минут и получи новый код на сайте.', callback_query_id=callback_query_id)
    active_dialog = _get_add_task_dialog(telegram_user_id)
    if action in {'add_task_quick_create', 'add_task_confirm_create'} and active_dialog and active_dialog.natural:
        return TelegramReply(chat_id=chat_id, text='Действие устарело. Открой подтверждение задачи заново.', callback_query_id=callback_query_id)
    if '|' in action:
        action, _, stamp = action.partition('|')
        dialog = _get_add_task_dialog(telegram_user_id)
        expected = f'{dialog.generation}:{DIALOG_STEPS.index(dialog.step)}' if dialog else None
        if stamp != expected:
            if action.startswith('add_task_reschedule_') or (dialog and dialog.edit_task_id):
                text, markup = task_views.stale()
                return TelegramReply(chat_id=chat_id, text=text, reply_markup=markup, callback_query_id=callback_query_id)
            return TelegramReply(chat_id=chat_id, text='Действие устарело. Начни заново: /add_task', callback_query_id=callback_query_id)
    command_kind = action if action in ({item['command'] for item in BOT_COMMANDS} | INTERNAL_BOT_COMMANDS) else 'callback' if callback_query_id else 'text'
    logger.info('Telegram stage=command update_id=%s command=%s', update.get('update_id'), command_kind)
    user = _telegram_user(db, telegram_user_id)
    if action == 'text' and user is None and len(argument) == 6 and argument.upper().isalnum() and conversational_intent(argument) is None:
        action = 'link'
        if not consume_limit(db, f'link:{telegram_user_id}', 5, 300):
            return TelegramReply(chat_id=chat_id, text='Слишком много попыток. Подожди 5 минут.', callback_query_id=callback_query_id)
    _update_linked_identity(db, user, chat_id=chat_id, sender=sender)

    dialog = _get_add_task_dialog(telegram_user_id)
    note_reply = telegram_notes.handle(
        db, user, telegram_user_id=telegram_user_id, action=action, argument=argument,
        site_url=_site_url(), special_active=bool(dialog and dialog.step in task_actions.RESCHEDULE_STEPS),
    )
    if note_reply is not None:
        return TelegramReply(chat_id=chat_id, text=note_reply[0], reply_markup=note_reply[1], callback_query_id=callback_query_id)

    if action == 'text':
        intent = conversational_intent(argument)
        if intent == 'cancel':
            action = 'cancel'
        elif intent and (_get_add_task_dialog(telegram_user_id) is None or _get_add_task_dialog(telegram_user_id).awaiting_phrase):
            action = intent

    reply_markup = None
    if action == 'greeting':
        response = 'Привет! Выбери нужный раздел или напиши задачу обычной фразой.' if user else build_start_unlinked_message()
        reply_markup = _main_keyboard() if user else _site_help_keyboard()
    elif action == 'thanks':
        response = 'Пожалуйста 🙂'
        reply_markup = _main_keyboard() if user else _site_help_keyboard()
    elif action == 'start':
        response = (
            build_start_linked_message(user)
            if user
            else build_start_unlinked_message()
        )
        reply_markup = _main_keyboard() if user else _site_help_keyboard()
    elif action == 'connect':
        response = build_start_linked_message(user) if user else build_connect_message()
        reply_markup = _main_keyboard() if user else _keyboard(
            [_url_button('🌐 Открыть сайт')], [_callback_button('← Назад', 'start')],
        )
    elif action in {'settings', 'connection_status'}:
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        elif action == 'settings':
            response = ('⚙️ <b>Настройки</b>\n\n' + class_reminders.settings_summary(db, user)
                        + '\n\n' + evening_digest.settings_summary(db, user) + '\n\nВыбери нужный раздел.')
            reply_markup = _settings_keyboard()
        else:
            name = user.workspace.display_name if user.workspace else _display_name(user)
            response = f'🔗 <b>Telegram подключён</b>\n\nПространство: <b>{_html(name)}</b>'
            reply_markup = _keyboard(_settings_back_button())
    elif action in {'class_settings', 'class_enable', 'class_disable', 'class_lead'} or action.startswith(('class_lead:', 'class_snooze:')):
        if user is None or user.telegram_chat_id != chat_id:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        elif action.startswith('class_snooze:'):
            response = class_reminders.request_snooze(db, user, action.partition(':')[2])
        else:
            if action in {'class_enable', 'class_disable'}:
                class_reminders.set_preferences(db, user, enabled=action == 'class_enable')
            elif action.startswith('class_lead:'):
                raw = action.partition(':')[2]
                if raw.isdigit() and int(raw) in class_reminders.LEAD_MINUTES:
                    class_reminders.set_preferences(db, user, lead=int(raw))
            response, reply_markup = class_reminders.settings_view(
                db, user, choose_lead=action == 'class_lead' or action.startswith('class_lead:'),
            )
    elif action in {'evening_settings', 'evening_enable', 'evening_disable', 'evening_time', 'evening_preview'} or action.startswith('evening_hour:'):
        if user is None or user.telegram_chat_id != chat_id:
            response, reply_markup = build_not_linked_message(), _site_help_keyboard()
        else:
            response, reply_markup = evening_digest.handle_settings(db, user, action, now_utc=digest_local_datetime(user))
    elif action in {'weekly_settings', 'weekly_enable', 'weekly_disable', 'weekly_day', 'weekly_time', 'weekly_preview'} or action.startswith(('weekly_day:', 'weekly_hour:')):
        if user is None:
            response, reply_markup = build_not_linked_message(), _site_help_keyboard()
        else:
            response, reply_markup = weekly_digest.settings_view(db, user, action, now_utc=digest_local_datetime(user))
    elif action == 'help':
        response = build_help_message()
        reply_markup = _help_keyboard() if user else _site_help_keyboard()
    elif action == 'cancel':
        cancelled = _clear_add_task_dialog(telegram_user_id)
        response = 'Действие отменено.' if cancelled else 'Сейчас нет активного действия.'
        reply_markup = _main_keyboard() if user else _site_help_keyboard()
    elif action == 'text':
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        else:
            dialog_result = _handle_add_task_dialog_action(
                db,
                user,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                action=action,
                argument=argument,
            )
            if dialog_result is None:
                response, reply_markup = _prepare_task_phrase(db, user, telegram_user_id=telegram_user_id, chat_id=chat_id, argument=argument)
            else:
                response, reply_markup = dialog_result
    elif action.startswith('add_task_'):
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        else:
            dialog_result = _handle_add_task_dialog_action(
                db,
                user,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                action=action,
                argument=argument,
            )
            if dialog_result is None:
                response = (
                    '⚠️ <b>Действие устарело</b>\n\n'
                    'Начни добавление задачи заново.'
                )
                reply_markup = _keyboard(
                    [_callback_button('➕ Добавить задачу', 'add_task_start')]
                )
            else:
                response, reply_markup = dialog_result
    elif action == 'link':
        if chat.get('type') not in {None, 'private'}:
            response = (
                '⚠️ <b>Подключение доступно только в личном чате</b>\n\n'
                'Открой диалог с ботом и повтори команду там.'
            )
            reply_markup = _site_help_keyboard()
        else:
            status = _link_account(
                db,
                code=argument,
                telegram_user_id=telegram_user_id,
                telegram_chat_id=chat_id,
                telegram_username=sender.get('username') if isinstance(sender.get('username'), str) else None,
            )
            if status == 'success':
                linked = _telegram_user(db, telegram_user_id)
                name = linked.workspace.display_name if linked.workspace else _display_name(linked)
                response = build_link_success_message() + f'\n\nПространство: <b>{_html(name)}</b>'
                reply_markup = _main_keyboard()
            else:
                response = build_link_error_message(status)
                reply_markup = (
                    _site_help_keyboard()
                    if status == 'missing'
                    else _keyboard([_url_button('🌐 Открыть сайт')])
                )
    elif action == 'now':
        response = build_now_message(db, user) if user else build_not_linked_message()
        reply_markup = _now_keyboard() if user else _site_help_keyboard()
    elif action == 'today':
        response = build_today_message(db, user) if user else build_not_linked_message()
        reply_markup = _today_keyboard() if user else _site_help_keyboard()
    elif action == 'today_schedule':
        response = build_today_schedule(db, user, now_utc=digest_local_datetime(user)) if user else build_not_linked_message()
        reply_markup = _today_schedule_keyboard() if user else _site_help_keyboard()
    elif action == 'tomorrow':
        response = build_tomorrow_message(db, user) if user else build_not_linked_message()
        reply_markup = _tomorrow_keyboard() if user else _site_help_keyboard()
    elif action == 'week_details':
        response = build_week_message(db, user) if user else build_not_linked_message()
        reply_markup = _keyboard([_callback_button('← Обзор недели', 'week')]) if user else _site_help_keyboard()
    elif action in {'week', 'week_next'} or action.startswith(('week_schedule:', 'week_view:')):
        if user is None:
            response, reply_markup = build_not_linked_message(), _site_help_keyboard()
        else:
            response, reply_markup = weekly_digest.view(db, user, action, now_utc=digest_local_datetime(user))
    elif action == 'tasks' or action.startswith('tasks_page:'):
        if user is None:
            response, reply_markup = build_not_linked_message(), _site_help_keyboard()
        else:
            raw_page = action.partition(':')[2] if action != 'tasks' else '0'
            page = int(raw_page) if raw_page.isdigit() and len(raw_page) < 8 else -1
            response, reply_markup, visible = task_views.task_page(db, user, digest_local_datetime(user).replace(tzinfo=None), page)
            if page >= 0 and (visible or action == 'tasks'):
                _remember_task_list(db, user, visible)
    elif action.startswith(('task_done:', 'task_restore:', 'task_reschedule:', 'task_edit:')):
        if user is None:
            response, reply_markup = build_not_linked_message(), _site_help_keyboard()
        else:
            try:
                result = task_actions.handle_action(db, user, action, digest_local_datetime(user).replace(tzinfo=None))
                if isinstance(result, Task):
                    if _get_add_task_dialog(telegram_user_id) is not None:
                        response, reply_markup = 'Есть незавершённое действие. Продолжи его или отмени.', _add_task_existing_dialog_keyboard()
                    else:
                        reschedule = action.startswith('task_reschedule:')
                        dialog = AddTaskDialog(user_id=user.id, chat_id=chat_id,
                            step=task_actions.RESCHEDULE if reschedule else ADD_TASK_WAITING_TITLE,
                            title=result.title, deadline=result.deadline, subject_id=result.subject_id,
                            subject_name=result.subject.name if result.subject else None, priority=result.priority,
                            natural=True, editing=not reschedule, edit_task_id=result.id,
                            task_revision=task_views.revision(db, result),
                            original_deadline=result.deadline.isoformat() if result.deadline else None)
                        _set_add_task_dialog(telegram_user_id, dialog)
                        response, reply_markup = _render_add_task_dialog_step(db, user, dialog)
                else:
                    response, reply_markup = result
            except task_actions.StaleTask:
                response, reply_markup = task_views.stale()
    elif (
        action in {'notifications', 'digest_toggle', 'deadline_toggle', 'deadline_settings'}
        or action.startswith('deadline_hours:')
    ):
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        else:
            notice = ''
            if action == 'digest_toggle':
                user.telegram_morning_digest_enabled = (
                    not user.telegram_morning_digest_enabled
                )
                if user.telegram_morning_digest_time is None:
                    user.telegram_morning_digest_time = time(hour=8)
                if not user.telegram_morning_digest_timezone:
                    user.telegram_morning_digest_timezone = settings.timezone
                notice = (
                    'Утренняя сводка включена ✅'
                    if user.telegram_morning_digest_enabled
                    else 'Утренняя сводка выключена.'
                )
                _commit(db)
            elif action == 'deadline_toggle':
                user.telegram_deadline_reminders_enabled = (
                    not user.telegram_deadline_reminders_enabled
                )
                if deadline_reminder_hours(user) not in VALID_DEADLINE_REMINDER_HOURS:
                    user.telegram_deadline_reminder_hours = 24
                notice = (
                    'Напоминания о дедлайнах включены ✅'
                    if user.telegram_deadline_reminders_enabled
                    else 'Напоминания о дедлайнах выключены.'
                )
                _commit(db)
            elif action.startswith('deadline_hours:'):
                raw_hours = action.partition(':')[2]
                hours = int(raw_hours) if raw_hours.isdigit() else 0
                if hours in VALID_DEADLINE_REMINDER_HOURS:
                    user.telegram_deadline_reminder_hours = hours
                    _commit(db)
                    notice = f'Буду напоминать примерно за {hours} ч.'
                else:
                    notice = 'Такой интервал не поддерживается.'

            if action == 'deadline_settings' or action == 'deadline_toggle' or action.startswith('deadline_hours:'):
                status = 'включены ✅' if user.telegram_deadline_reminders_enabled else 'выключены'
                response = (f'{notice}\n\n' if notice else '') + (
                    '⏰ <b>Напоминания о дедлайнах</b>\n\n'
                    f'Статус: <b>{status}</b>\n'
                    f'Напоминать за: <b>{deadline_reminder_hours(user)} ч.</b>'
                )
                reply_markup = _deadline_keyboard(user)
            else:
                response = (f'{notice}\n\n' if notice else '') + build_notifications_settings_message(user)
                reply_markup = _notifications_keyboard(user)
    elif action in {'digest', 'digest_on', 'digest_off', 'digest_test'}:
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        elif action == 'digest_test':
            response = build_morning_digest_message(db, user)
            reply_markup = _digest_summary_keyboard()
        else:
            status_notice = ''
            if action == 'digest_on':
                user.telegram_morning_digest_enabled = True
                if user.telegram_morning_digest_time is None:
                    user.telegram_morning_digest_time = time(hour=8)
                if not user.telegram_morning_digest_timezone:
                    user.telegram_morning_digest_timezone = settings.timezone
                _commit(db)
                status_notice = 'Утренняя сводка включена ✅\n\n'
            elif action == 'digest_off':
                user.telegram_morning_digest_enabled = False
                _commit(db)
                status_notice = 'Утренняя сводка выключена.\n\n'
            response = status_notice + build_digest_settings_message(user)
            reply_markup = _digest_keyboard(user)
    elif action == 'done' or action.startswith('done_task:'):
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        elif action == 'done' and not argument:
            response = build_done_help_message()
            reply_markup = _add_task_navigation_keyboard()
        else:
            callback_task_id = None
            if action.startswith('done_task:'):
                raw_task_id = action.partition(':')[2]
                callback_task_id = int(raw_task_id) if raw_task_id.isdigit() else -1
            try:
                status, task = _resolve_done_task(
                    db,
                    user,
                    argument,
                    task_id=callback_task_id,
                )
            except Exception:
                db.rollback()
                logger.error('Telegram task completion failed.')
                status, task = 'error', None

            if status == 'error':
                response = (
                    '⚠️ <b>Не удалось закрыть задачу</b>\n\n'
                    'Произошла ошибка. Попробуй ещё раз позже.'
                )
                reply_markup = _done_error_keyboard()
            else:
                if status == 'success':
                    remaining = db.query(Task).filter(Task.user_id == user.id, Task.is_completed.is_(False)).count()
                    response, reply_markup = task_views.after_done(db, task, remaining)
                else:
                    response, reply_markup = build_done_result_message(status, task), _done_error_keyboard()
    elif action == 'add_task':
        if user is None:
            response = build_not_linked_message()
            reply_markup = _site_help_keyboard()
        elif not argument:
            dialog_result = _handle_add_task_dialog_action(
                db,
                user,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                action='add_task_start',
                argument='',
            )
            response, reply_markup = dialog_result
        else:
            try:
                result = create_telegram_task(db, user, argument)
            except ValueError as error:
                response = (
                    '⚠️ <b>Не удалось добавить задачу</b>\n\n'
                    f'{_html(error)}'
                )
                reply_markup = _add_task_navigation_keyboard()
            except Exception:
                db.rollback()
                logger.error('Telegram task creation failed.')
                response = (
                    '⚠️ <b>Не удалось добавить задачу</b>\n\n'
                    'Произошла ошибка. Попробуй ещё раз позже.'
                )
                reply_markup = _add_task_navigation_keyboard()
            else:
                _clear_add_task_dialog(telegram_user_id)
                response = build_add_task_success_message(result)
                reply_markup = _add_task_success_keyboard()
    elif action == 'site':
        response = build_site_message()
        reply_markup = _keyboard([_url_button('Открыть Student Assistant')])
    elif action == 'unlink':
        if user is None:
            response = (
                '⚠️ <b>Telegram пока не подключён</b>\n\n'
                'Сначала подключи аккаунт через профиль на сайте.'
            )
            reply_markup = _keyboard([_url_button('🌐 Открыть сайт')])
        else:
            response = build_unlink_confirm_message()
            reply_markup = _unlink_keyboard()
    elif action == 'unlink_confirm':
        if user is None:
            response = '⚠️ <b>Telegram уже отключён</b>'
        else:
            _clear_add_task_dialog(telegram_user_id)
            clear_telegram_link(user)
            _commit(db)
            response = (
                '✅ <b>Telegram отключён</b>\n\n'
                'Ты сможешь подключить его заново в профиле Student Assistant.'
            )
        reply_markup = _keyboard([_url_button('🌐 Открыть сайт')])
    elif action == 'unlink_cancel':
        response = 'Отмена выполнена ✅\nTelegram остаётся подключён.'
        reply_markup = _main_keyboard()
    else:
        response = build_unknown_command_message()
        reply_markup = _main_keyboard() if user else _site_help_keyboard()

    return TelegramReply(
        chat_id=chat_id,
        text=response,
        reply_markup=reply_markup,
        callback_query_id=callback_query_id,
        chat_action=(
            'typing'
            if (
                action
                in {
                    'start',
                    'today',
                    'tomorrow',
                    'week',
                    'tasks',
                    'notifications',
                    'digest_toggle',
                    'deadline_toggle',
                    'digest',
                    'digest_on',
                    'digest_off',
                    'digest_test',
                    'done',
                    'cancel',
                    'help',
                    'add_task',
                }
                or action.startswith('done_task:')
                or action.startswith('add_task_')
                or action.startswith('deadline_hours:')
                or action == 'text'
            )
            else None
        ),
    )


def handle_telegram_update(db: Session, update: dict) -> TelegramReply | None:
    message = update.get('callback_query') or update.get('message') or {}
    sender = message.get('from') if isinstance(message, dict) else None
    chat_message = message.get('message', message) if isinstance(message, dict) else {}
    chat = chat_message.get('chat', {}) if isinstance(chat_message, dict) else {}
    if not isinstance(sender, dict) or type(sender.get('id')) is not int or not isinstance(chat, dict) or chat.get('type') != 'private':
        return _handle_telegram_update(db, update)
    row = state_row(db, f'dialog:{sender["id"]}')
    context = {}
    if row.expires_at > utcnow() and row.data:
        data = dict(row.data)
        if data.get('deadline'):
            data['deadline'] = datetime.fromisoformat(data['deadline'])
        context['dialog'] = AddTaskDialog(**data)
    token = _DIALOG_CONTEXT.set(context)
    user = _telegram_user(db, sender['id'])
    date_token = _USER_DATE.set(digest_local_datetime(user).date() if user else None)
    try:
        reply = _handle_telegram_update(db, update)
        dialog = context.get('dialog')
        if reply and reply.reply_markup and dialog:
            rows = reply.reply_markup.get('inline_keyboard', [])
            if not any(button.get('callback_data', '').split('|', 1)[0] == 'add_task_cancel'
                       or button.get('callback_data', '').startswith('note_cancel:')
                       for buttons in rows for button in buttons):
                rows.append([_callback_button('❌ Отменить', 'add_task_cancel')])
            for buttons in reply.reply_markup.get('inline_keyboard', []):
                for button in buttons:
                    action = button.get('callback_data', '')
                    if action.startswith('add_task_') and action not in {'add_task_start', 'add_task_help'}:
                        button['callback_data'] = f'{action}|{dialog.generation}:{DIALOG_STEPS.index(dialog.step)}'
        data = asdict(dialog) if dialog else {}
        if data.get('deadline'):
            data['deadline'] = data['deadline'].isoformat()
        row.data = data
        row.expires_at = utcnow() + timedelta(minutes=30)
        _commit(db)
        return reply
    finally:
        _DIALOG_CONTEXT.reset(token)
        _USER_DATE.reset(date_token)


def call_telegram_api(method: str, payload: dict, *, request_timeout: int = 12) -> dict:
    if not settings.telegram_bot_token:
        raise TelegramAPIError(category='missing_token')

    url = f'{TELEGRAM_API_ORIGIN}/bot{settings.telegram_bot_token}/{method}'
    body = json.dumps(payload).encode('utf-8')
    request = Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=request_timeout) as response:
            result = json.loads(response.read().decode('utf-8'))
            status = response.status
    except HTTPError as error:
        status = error.code
        try:
            result = json.loads(error.read().decode('utf-8'))
        except (ValueError, OSError):
            result = {}
    except (URLError, TimeoutError, OSError):
        raise TelegramAPIError(category='network') from None
    except (ValueError, UnicodeError):
        raise TelegramAPIError(category='temporary') from None

    if not isinstance(result, dict):
        raise TelegramAPIError(category='temporary', status=status)
    if not result.get('ok'):
        error_code = result.get('error_code')
        if type(error_code) is int:
            status = error_code
        category = {401: 'invalid_token', 403: 'blocked', 409: 'receiver_conflict',
                    429: 'rate_limit', 404: 'invalid_token', 400: 'bad_request'}.get(status, 'temporary' if status >= 500 else 'rejected')
        if status == 400 and 'chat not found' in str(result.get('description', '')).lower():
            category = 'chat_not_found'
        parameters = result.get('parameters')
        retry_after = parameters.get('retry_after') if isinstance(parameters, dict) else None
        raise TelegramAPIError(category=category, status=status,
                               retry_after=retry_after if type(retry_after) is int else None) from None
    return result


def send_telegram_message(reply: TelegramReply) -> None:
    if reply.callback_query_id:
        try:
            call_telegram_api(
                'answerCallbackQuery',
                {'callback_query_id': reply.callback_query_id},
                request_timeout=2,
            )
        except TelegramAPIError:
            logger.warning('Telegram callback acknowledgement failed.')

    if reply.chat_action:
        try:
            call_telegram_api(
                'sendChatAction',
                {
                    'chat_id': reply.chat_id,
                    'action': reply.chat_action,
                },
                request_timeout=2,
            )
        except TelegramAPIError:
            logger.warning('Telegram chat action failed.')

    chunks = [(reply.text, reply.parse_mode)]
    if len(reply.text.encode('utf-16-le')) // 2 > 3900:
        from html.parser import HTMLParser
        class PlainText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, data):
                self.parts.append(data)
        parser = PlainText()
        parser.feed(reply.text)
        plain = ''.join(parser.parts)
        chunks = [(plain[i:i + 1900], None) for i in range(0, len(plain), 1900)]
    for index, (text, mode) in enumerate(chunks):
        payload = {'chat_id': reply.chat_id, 'text': text, 'disable_web_page_preview': True}
        if mode:
            payload['parse_mode'] = mode
        if reply.reply_markup and index == len(chunks) - 1:
            payload['reply_markup'] = reply.reply_markup
        call_telegram_api('sendMessage', payload)


def install_telegram_webhook(webhook_url: str) -> None:
    call_telegram_api(
        'setWebhook',
        {
            'url': webhook_url,
            'secret_token': settings.telegram_webhook_secret,
            'allowed_updates': ['message', 'callback_query'],
            'drop_pending_updates': False,
        },
    )


def install_telegram_commands() -> None:
    call_telegram_api(
        'setMyCommands',
        {
            'commands': BOT_COMMANDS,
        },
    )


def delete_telegram_webhook() -> None:
    call_telegram_api(
        'deleteWebhook',
        {
            'drop_pending_updates': False,
        },
    )


def get_telegram_updates(*, offset: int | None = None, timeout: int = 25) -> list[dict]:
    payload: dict[str, object] = {
        'timeout': timeout,
        'allowed_updates': ['message', 'callback_query'],
    }
    if offset is not None:
        payload['offset'] = offset

    response = call_telegram_api(
        'getUpdates',
        payload,
        request_timeout=timeout + 10,
    )
    updates = response.get('result')
    if not isinstance(updates, list):
        raise TelegramAPIError('Telegram API returned an invalid updates payload.')
    return [update for update in updates if isinstance(update, dict)]
