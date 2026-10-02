"""Compact evening summary over shared tasks/calendar and durable Telegram state."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html import escape

from ..core.time import APP_ZONE
from ..models import Task, TelegramState
from .telegram_day import TelegramCalendar, has_complete_time
from .telegram_digest import digest_local_datetime
from .telegram_state import state_row
from .telegram_task_draft import button, keyboard
from .telegram_task_views import active_tasks
from .telegram_today import DIVIDER, _task_line, _task_rank, plural

HOURS = (19, 20, 21, 22)
GRACE = timedelta(minutes=15)


def preferences(db, user):
    row = db.get(TelegramState, f'evening-settings:{user.id}')
    data = row.data if row else {}
    hour = data.get('hour', 21)
    return {'enabled': data.get('enabled') is True, 'hour': hour if hour in HOURS else 21}


def set_preferences(db, user, *, enabled=None, hour=None):
    row = state_row(db, f'evening-settings:{user.id}')
    data = preferences(db, user)
    if enabled is not None:
        data['enabled'] = bool(enabled)
    if hour in HOURS:
        data['hour'] = hour
    row.data = data
    row.expires_at = datetime(9999, 1, 1)
    db.flush()
    return data


def settings_summary(db, user):
    pref = preferences(db, user)
    return f'🌙 Вечерняя сводка: {"✅" if pref["enabled"] else "❌"}\n🕘 Время: {pref["hour"]}:00'


def settings_view(db, user, *, choose_time=False):
    pref = preferences(db, user)
    text = (f'🌙 <b>Вечерняя сводка</b>\n\nСтатус: {"включена" if pref["enabled"] else "выключена"}'
            f'\nВремя: {pref["hour"]}:00')
    if choose_time:
        buttons = [button(f'{"✅ " if hour == pref["hour"] else ""}{hour}:00', f'evening_hour:{hour}') for hour in HOURS]
        rows = [buttons[:2], buttons[2:], [button('← Назад', 'evening_settings')]]
    else:
        rows = [[button('🔔 Выключить' if pref['enabled'] else '🔔 Включить',
                        'evening_disable' if pref['enabled'] else 'evening_enable')],
                [button('🕘 Изменить время', 'evening_time')],
                [button('🧪 Показать сейчас', 'evening_preview')],
                [button('← Назад', 'settings')]]
    return text, keyboard(*rows)


def digest_keyboard(*, preview=False):
    markup = keyboard([button('📆 Завтра', 'tomorrow'), button('📌 Задачи', 'tasks')],
                      [button('📝 Заметка', 'note_start')])
    if preview:
        markup['inline_keyboard'].append([button('← Назад', 'evening_settings')])
    return markup


@dataclass
class EveningSummary:
    completed: int
    active: int
    overdue: int
    tomorrow_deadlines: int
    lessons: list[dict]
    important: Task | None
    local_now: datetime


def completed_today(db, user, local_now):
    # complete_task() (website + Telegram) writes naive PROJECT-local time.
    # Deadlines, unlike completed_at, are user-local wall-clock values.
    start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    end = start + timedelta(days=1)
    def project(value):
        return value.astimezone(APP_ZONE).replace(tzinfo=None)
    return db.query(Task).filter(
        Task.user_id == user.id, Task.is_completed.is_(True),
        Task.completed_at >= project(start), Task.completed_at < project(end),
        Task.completed_at <= project(local_now),
    ).count()


def collect_summary(db, user, *, now_utc=None):
    local = digest_local_datetime(user, now_utc)
    now = local.replace(tzinfo=None)
    tomorrow = now.date() + timedelta(days=1)
    tasks = active_tasks(db, user, now)
    overdue = [task for task in tasks if task.deadline and _task_rank(task, now) == 0]
    due_tomorrow = [task for task in tasks if task.deadline and task.deadline.date() == tomorrow]
    # Keep the shared ordering inside each group; only the evening group
    # precedence differs from /today: overdue, tomorrow, high, nearest deadline.
    high = [task for task in tasks if task.priority == 'high']
    nearest = sorted((task for task in tasks if task.deadline), key=lambda task: (task.deadline, task.id))
    candidates = overdue or due_tomorrow or high or nearest
    return EveningSummary(
        completed=completed_today(db, user, local), active=len(tasks), overdue=len(overdue),
        tomorrow_deadlines=len(due_tomorrow),
        lessons=TelegramCalendar(db, user, local).day(tomorrow).lessons,
        important=candidates[0] if candidates else None, local_now=now,
    )


def render_summary(summary):
    counters = []
    if summary.completed:
        counters.append(f'✅ Выполнено сегодня: {summary.completed}')
        if not summary.active:
            counters.append('На сегодня всё ✅')
    if summary.active:
        counters.append(f'📌 Осталось активных: {summary.active}')
    if summary.overdue:
        counters.append(f'⚠️ Просрочено: {summary.overdue}')
    sections = ['🌙 <b>Итоги дня</b>', '\n'.join(counters) or 'На сегодня всё ✅']
    tomorrow = ['📆 <b>Завтра</b>']
    if summary.lessons:
        tomorrow.append('🎓 ' + plural(len(summary.lessons), 'занятие', 'занятия', 'занятий'))
        first = summary.lessons[0]
        if all(has_complete_time(lesson) for lesson in summary.lessons):
            title = first['title'][:80] + ('…' if len(first['title']) > 80 else '')
            tomorrow.append(f'Первая пара: {escape(title, quote=False)} · {first["start"]:%H:%M}')
        else:
            tomorrow.append('Время занятий указано не полностью — открой «Завтра».')
    else:
        tomorrow.append('🌿 Завтра без занятий')
    if summary.tomorrow_deadlines:
        tomorrow.append('📌 ' + plural(summary.tomorrow_deadlines, 'задача', 'задачи', 'задач') + ' с дедлайном')
    elif not summary.important:
        tomorrow.append('📌 Срочных задач нет')
    sections += [DIVIDER, '\n'.join(tomorrow)]
    if summary.important:
        task = summary.important
        if task.deadline and task.deadline.date() == summary.local_now.date() + timedelta(days=1):
            line = f'{escape(task.title, quote=False)} · завтра до {task.deadline:%H:%M}'
        elif not task.deadline:
            line = f'{escape(task.title, quote=False)} · высокий приоритет'
        else:
            line = _task_line(task, summary.local_now)
        sections += [DIVIDER, '🔴 <b>Не забудь</b>\n' + line]
    return '\n\n'.join(sections)


def build_evening_digest_message(db, user, *, now_utc=None):
    return render_summary(collect_summary(db, user, now_utc=now_utc))


def handle_settings(db, user, action, *, now_utc=None):
    if action == 'evening_preview':
        return build_evening_digest_message(db, user, now_utc=now_utc), digest_keyboard(preview=True)
    if action in {'evening_enable', 'evening_disable'}:
        set_preferences(db, user, enabled=action == 'evening_enable')
    elif action.startswith('evening_hour:'):
        value = action.partition(':')[2]
        if value in {str(hour) for hour in HOURS}:
            set_preferences(db, user, hour=int(value))
    return settings_view(db, user, choose_time=action == 'evening_time' or action.startswith('evening_hour:'))


def is_due(db, user, current):
    pref = preferences(db, user)
    if not pref['enabled'] or not user.telegram_user_id or not user.telegram_chat_id or user.telegram_chat_id <= 0:
        return False
    local = digest_local_datetime(user, current).replace(tzinfo=None)
    due = datetime.combine(local.date(), time(pref['hour']))
    return timedelta(0) <= local - due <= GRACE
