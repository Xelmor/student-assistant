"""Calendar-week snapshots, compact views and preferences; no delivery or API calls."""
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import escape

from ..core.time import APP_ZONE
from ..models import Task, TelegramState
from .calendar_service import MONTH_NAMES_RU_GENITIVE
from .telegram_day import TelegramCalendar, format_interval, has_complete_time
from .telegram_digest import digest_local_datetime
from .telegram_state import state_row
from .telegram_task_draft import button, keyboard
from .telegram_task_views import active_tasks
from .telegram_today import _task_rank

DAYS = (4, 5, 6)
HOURS = (18, 19, 20, 21)
DAY_NAMES = ('Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье')
DAY_SHORT = ('ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС')
GRACE = timedelta(minutes=15)
PAGE_BUDGET = 3000  # HTML source, comfortably below Telegram's rendered UTF-16 limit.


def week_start(local):
    day = local.date() if isinstance(local, datetime) else local
    return day - timedelta(days=day.weekday())


def date_label(day):
    return f'{day.day} {MONTH_NAMES_RU_GENITIVE[day.month]}'


def range_label(start):
    end = start + timedelta(days=6)
    if start.year != end.year:
        return f'{date_label(start)} {start.year} — {date_label(end)} {end.year}'
    if start.month == end.month:
        return f'{start.day}–{date_label(end)}'
    return f'{date_label(start)} — {date_label(end)}'


def short(value, limit=100):
    return escape(value[:limit] + ('…' if len(value) > limit else ''), quote=False)


def completed_in_week(db, user, start, local):
    first = datetime.combine(start, time.min, tzinfo=local.tzinfo)
    end = first + timedelta(days=7)
    def project(value):
        return value.astimezone(APP_ZONE).replace(tzinfo=None)
    return db.query(Task).filter(
        Task.user_id == user.id, Task.is_completed.is_(True),
        Task.completed_at >= project(first), Task.completed_at < project(end),
        Task.completed_at <= project(local),
    ).count()


def lesson_duration(lesson, zone):
    if not has_complete_time(lesson):
        return None
    instants = []
    for value in (lesson['start'], lesson['end']):
        instant = value.replace(tzinfo=zone).astimezone(UTC)
        # Nonexistent wall-clock values at a DST jump have no reliable duration.
        if instant.astimezone(zone).replace(tzinfo=None) != value:
            return None
        instants.append(instant)
    duration = instants[1] - instants[0]
    return duration if duration > timedelta(0) else None


@dataclass
class WeeklySummary:
    start: date
    local_now: datetime
    days: list[tuple[date, list[dict]]]
    lesson_count: int
    duration: timedelta
    unknown_durations: int
    completed: int
    active: int
    overdue: int
    deadlines: int
    important: Task | None

    @property
    def future(self):
        return self.start > week_start(self.local_now)


def collect_week(db, user, *, now_utc=None, start=None):
    local = digest_local_datetime(user, now_utc)
    now = local.replace(tzinfo=None)
    start = start or week_start(local)
    end = start + timedelta(days=7)
    calendar = TelegramCalendar(db, user, local)
    days = [(start + timedelta(days=i), calendar.day(start + timedelta(days=i)).lessons) for i in range(7)]
    lessons = [lesson for _, values in days for lesson in values]
    durations = [lesson_duration(lesson, local.tzinfo) for lesson in lessons]
    tasks = active_tasks(db, user, now)
    overdue = [task for task in tasks if task.deadline and _task_rank(task, now) == 0]
    deadlines = sorted((task for task in tasks if task.deadline and start <= task.deadline.date() < end), key=lambda task: (task.deadline, task.id))
    if start > week_start(local):
        # A future-week view must not be dominated by this week's overdue work.
        candidates = deadlines
    else:
        today = [task for task in tasks if task.deadline and task.deadline.date() == now.date()]
        high = [task for task in tasks if task.priority == 'high']
        future = sorted((task for task in tasks if task.deadline and task.deadline >= now), key=lambda task: (task.deadline, task.id))
        candidates = overdue or today or deadlines or high or future
    return WeeklySummary(start, now, days, len(lessons), sum((d for d in durations if d is not None), timedelta()),
                         sum(d is None for d in durations),
                         0 if start > week_start(local) else completed_in_week(db, user, start, local),
                         len(tasks), len(overdue), len(deadlines), candidates[0] if candidates else None)


def important_text(summary):
    task = summary.important
    if not task:
        return ''
    title = short(task.title)
    if not task.deadline:
        detail = 'Высокий приоритет'
    elif task.deadline < summary.local_now:
        detail = f'Просрочено · {task.deadline:%d.%m, %H:%M}'
    elif task.deadline.date() == summary.local_now.date():
        detail = f'Сегодня до {task.deadline:%H:%M}'
    else:
        detail = f'{DAY_NAMES[task.deadline.weekday()]} · {task.deadline:%d.%m} до {task.deadline:%H:%M}'
    return f'🔴 <b>Главное</b>\n{title}\n{detail}'


def render_week(summary, *, automatic=False):
    current = week_start(summary.local_now)
    label = 'Эта неделя' if summary.start == current else 'Следующая неделя' if summary.start == current + timedelta(days=7) else 'Неделя'
    lines = [f'📊 <b>{label}</b>\n{range_label(summary.start)}']
    stats = []
    if summary.lesson_count:
        stats.append(f'🎓 Занятий: {summary.lesson_count}')
        if summary.duration:
            label = 'Известное учебное время' if summary.unknown_durations else 'Учебное время'
            stats.append(f'⏱ {label}: {format_interval(summary.duration)}')
        if summary.unknown_durations:
            stats.append('⏱ У части занятий время указано не полностью.')
    elif summary.future and not summary.deadlines:
        stats.append('🌿 Следующая неделя пока свободна')
    else:
        stats.append('🌿 На следующей неделе занятий нет' if summary.future else '🌿 На этой неделе занятий нет')
    if summary.future:
        if summary.deadlines:
            stats.append(f'📌 Дедлайнов: {summary.deadlines}')
    else:
        if summary.completed:
            stats.append(f'✅ Выполнено задач: {summary.completed}')
        stats.append(f'📌 Активных: {summary.active}' if summary.active else '✅ Активных задач нет')
        if summary.overdue:
            stats.append(f'⚠️ Просрочено: {summary.overdue}')
    lines.append('\n'.join(stats))
    if automatic and summary.lesson_count:
        if not summary.unknown_durations:
            first = next(lesson for _, lessons in summary.days for lesson in lessons)
            lines.append(f'Первая пара:\n{DAY_NAMES[first["start"].weekday()]} · {first["start"]:%H:%M} · {short(first["title"], 80)}')
        else:
            lines.append('Уточни время первой пары в расписании.')
    if summary.important:
        lines.append(important_text(summary))
    return '\n\n'.join(lines)


def overview_keyboard(start, local_now):
    rows = [[button('📅 Расписание', f'week_schedule:{start}:0')]]
    if start == week_start(local_now):
        rows.append([button('➡️ Следующая неделя', 'week_next')])
        rows.append([button('📋 События и дедлайны', 'week_details')])
    else:
        rows.append([button('⬅️ Эта неделя', 'week')])
    rows += [[button('📌 Задачи', 'tasks')], [button('← Главное меню', 'start')]]
    return keyboard(*rows)


def automatic_start(user, current):
    return week_start(digest_local_datetime(user, current)) + timedelta(days=7)


def automatic_message(db, user, *, now_utc=None):
    return render_week(collect_week(db, user, now_utc=now_utc, start=automatic_start(user, now_utc)), automatic=True)


def automatic_keyboard(user, current):
    start = automatic_start(user, current)
    return keyboard([button('📅 Расписание', f'week_schedule:{start}:0'), button('📌 Задачи', 'tasks')],
                    [button('⚙️ Настройки', 'weekly_settings')])


def delivery_key(user, current):
    return f'weekly-digest:{user.id}:{automatic_start(user, current)}'


def schedule_pages(summary):
    # Split at complete rows, repeating the day label when a busy day spans pages.
    def units(text):
        return len(text.encode('utf-16-le')) // 2
    pages, blocks, size = [], [], 0
    for day, lessons in summary.days:
        heading = f'<b>{DAY_SHORT[day.weekday()]} · {date_label(day)}</b>'
        rows = []
        for lesson in lessons:
            if lesson['type'] == 'schedule-change' and not lesson.get('raw_start_time'):
                timing = 'Время не указано'
            else:
                timing = f'{lesson["start"]:%H:%M}'
            room = short((lesson.get('room') or '').strip(), 50)
            rows.append(f'{timing} {short(lesson["title"])}' + (f' · Ауд. {room}' if room else ''))
        rows = rows or ['🌿 Нет занятий']
        block = heading
        for row in rows:
            if size + units(block) + units(row) + 5 > PAGE_BUDGET:
                if block != heading:
                    blocks.append(block)
                if blocks:
                    pages.append('\n\n'.join(blocks))
                blocks, size, block = [], 0, heading
            block += '\n' + row
        blocks.append(block)
        size += units(block) + 2
    if blocks:
        pages.append('\n\n'.join(blocks))
    return pages


def parse_start(value, local):
    try:
        start = date.fromisoformat(value)
    except ValueError:
        return None
    return start if start.weekday() == 0 and abs((start - week_start(local)).days) <= 364 else None


def view(db, user, action, *, now_utc=None):
    local = digest_local_datetime(user, now_utc)
    start = week_start(local) + (timedelta(days=7) if action == 'week_next' else timedelta())
    page = 0
    if ':' in action:
        parts = action.split(':')
        start = parse_start(parts[1], local)
        if len(parts) == 3 and parts[2].isascii() and parts[2].isdigit() and len(parts[2]) <= 5:
            page = int(parts[2])
        elif action.startswith('week_schedule:'):
            start = None
        elif len(parts) != 2:
            start = None
    if start is None:
        return '⚠️ Этот обзор устарел. Открой неделю заново.', keyboard([button('🗓 Неделя', 'week')])
    summary = collect_week(db, user, now_utc=local, start=start)
    if action.startswith('week_schedule:'):
        pages = schedule_pages(summary)
        if page >= len(pages):
            return '⚠️ Расписание изменилось. Открой его заново.', overview_keyboard(start, local)
        navigation = []
        if page:
            navigation.append(button('← Предыдущая страница', f'week_schedule:{start}:{page-1}'))
        if page + 1 < len(pages):
            navigation.append(button('Следующая страница →', f'week_schedule:{start}:{page+1}'))
        rows = [navigation] if navigation else []
        rows += [[button('← Обзор недели', f'week_view:{start}')],
                 [button('➡️ Следующая неделя', 'week_next') if start == week_start(local) else button('⬅️ Эта неделя', 'week')]]
        label = f'\nСтраница {page+1}/{len(pages)}' if len(pages) > 1 else ''
        return f'🗓 <b>{range_label(start)}</b>{label}\n\n{pages[page]}', keyboard(*rows)
    return render_week(summary), overview_keyboard(start, local)


def preferences(db, user):
    row = db.get(TelegramState, f'weekly-settings:{user.id}')
    data = row.data if row else {}
    return {'enabled': data.get('enabled') is True,
            'day': data.get('day') if data.get('day') in DAYS else 6,
            'hour': data.get('hour') if data.get('hour') in HOURS else 19}


def set_preferences(db, user, *, enabled=None, day=None, hour=None):
    row = state_row(db, f'weekly-settings:{user.id}')
    data = preferences(db, user)
    if enabled is not None:
        data['enabled'] = bool(enabled)
    if day in DAYS:
        data['day'] = day
    if hour in HOURS:
        data['hour'] = hour
    row.data, row.expires_at = data, datetime(9999, 1, 1)
    db.flush()
    return data


def settings_view(db, user, action='weekly_settings', *, now_utc=None):
    if action == 'weekly_preview':
        markup = automatic_keyboard(user, now_utc)
        markup['inline_keyboard'].append([button('← Назад', 'weekly_settings')])
        return automatic_message(db, user, now_utc=now_utc), markup
    if action in {'weekly_enable', 'weekly_disable'}:
        set_preferences(db, user, enabled=action == 'weekly_enable')
    for kind, values in [('day', DAYS), ('hour', HOURS)]:
        if action.startswith(f'weekly_{kind}:') and action.partition(':')[2] in {str(v) for v in values}:
            set_preferences(db, user, **{kind: int(action.partition(':')[2])})
    pref = preferences(db, user)
    text = (f'📊 <b>Недельный обзор</b>\n\nСтатус: {"✅" if pref["enabled"] else "❌"}'
            f'\nДень: {DAY_NAMES[pref["day"]].lower()}\nВремя: {pref["hour"]}:00')
    if action == 'weekly_day' or action.startswith('weekly_day:'):
        rows = [[button(('✅ ' if day == pref['day'] else '') + DAY_SHORT[day].title(), f'weekly_day:{day}') for day in DAYS], [button('← Назад', 'weekly_settings')]]
    elif action == 'weekly_time' or action.startswith('weekly_hour:'):
        options = [button(f'{"✅ " if hour == pref["hour"] else ""}{hour}:00', f'weekly_hour:{hour}') for hour in HOURS]
        rows = [options[:2], options[2:], [button('← Назад', 'weekly_settings')]]
    else:
        rows = [[button('🔔 Выключить' if pref['enabled'] else '🔔 Включить', 'weekly_disable' if pref['enabled'] else 'weekly_enable')],
                [button('📅 Изменить день', 'weekly_day'), button('🕘 Изменить время', 'weekly_time')],
                [button('🧪 Показать сейчас', 'weekly_preview')], [button('← Назад', 'settings')]]
    return text, keyboard(*rows)


def is_due(db, user, current):
    pref = preferences(db, user)
    if not pref['enabled'] or not user.telegram_user_id or not user.telegram_chat_id or user.telegram_chat_id <= 0:
        return False
    local = digest_local_datetime(user, current).replace(tzinfo=None)
    due = datetime.combine(local.date(), time(pref['hour']))
    return local.weekday() == pref['day'] and timedelta(0) <= local - due <= GRACE
