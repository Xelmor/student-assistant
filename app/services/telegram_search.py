"""Deterministic, owner-scoped Telegram search over live website records."""
from datetime import UTC, datetime, timedelta
from html import escape
import re
import secrets
import unicodedata

from ..models import Note, ScheduleItem, Subject, Task, TelegramState
from .telegram_day import TelegramCalendar
from .telegram_notes import binding, button, keyboard
from .telegram_state import state_row, utcnow
from .telegram_today import _time

TTL = timedelta(minutes=30)
HORIZON_DAYS = 30
PAGE_SIZE = 5
MAX_QUERY = 200
PREFIX = re.compile(r'^(?:поиск|найти)\s*:\s*(.*)$', re.IGNORECASE | re.DOTALL)
GROUPS = {'tasks': ('📌 Задачи', 'задач'), 'notes': ('📝 Заметки', 'заметок'),
          'classes': ('🎓 Занятия', 'занятий')}


def normalize_query(value):
    value = unicodedata.normalize('NFKC', value).casefold().replace('ё', 'е')
    return ' '.join(''.join(char if char.isalnum() else ' ' for char in value).split())


def relevance(query, title, *other):
    title = normalize_query(title or '')
    if title == query:
        return 0
    if title.startswith(query):
        return 1
    if query in title or all(token in title for token in query.split()):
        return 2
    fields = ' '.join([title, *(normalize_query(field or '') for field in other)])
    return 3 if all(token in fields for token in query.split()) else None


def rank_results(results):
    return sorted(results, key=lambda result: result['rank'])


def search_tasks(db, user, query, now):
    # Scope BOTH sides of the join, including malformed cross-owner relations.
    rows = db.query(Task, Subject.name).outerjoin(
        Subject, (Task.subject_id == Subject.id) & (Subject.user_id == user.id),
    ).filter(Task.user_id == user.id).all()
    results = []
    for task, subject in rows:
        score = relevance(query, task.title, subject, task.description)
        if score is None:
            continue
        deadline = task.deadline
        urgency = 3 if deadline is None else 0 if deadline < now else 1 if deadline.date() == now.date() else 2
        if task.is_completed:
            details = '✅ Выполнено'
        elif deadline:
            label = 'Сегодня' if deadline.date() == now.date() else 'Завтра' if deadline.date() == (now + timedelta(days=1)).date() else deadline.strftime('%d.%m.%Y')
            details = ('⚠️ Просрочено · ' if urgency == 0 else '') + f'{label} · {deadline:%H:%M}'
        else:
            details = 'Без дедлайна'
        if task.priority == 'high' and not task.is_completed:
            details += ' · высокий приоритет'
        results.append({'id': task.id, 'title': task.title, 'details': details,
                        'rank': (bool(task.is_completed), score, urgency, deadline or datetime.max, task.id)})
    return rank_results(results)


def search_notes(db, user, query):
    results = []
    for note in db.query(Note).filter(Note.user_id == user.id).all():
        score = relevance(query, note.title, note.content)
        if score is not None:
            created = note.created_at or datetime.min
            results.append({'id': note.id, 'title': note.title, 'details': note.content or '',
                            'rank': (score, -created.toordinal(), -created.hour, -created.minute,
                                     -created.second, -created.microsecond, -note.id)})
    return rank_results(results)


def search_classes(db, user, query, local_now):
    calendar = TelegramCalendar(db, user, local_now)
    subjects = {subject.id: subject for subject in db.query(Subject).filter(Subject.user_id == user.id).all()}
    slots = dict(db.query(ScheduleItem.id, ScheduleItem.subject_id).join(
        Subject, (ScheduleItem.subject_id == Subject.id) & (Subject.user_id == user.id),
    ).filter(ScheduleItem.user_id == user.id).all())
    results = []
    instant = local_now.astimezone(UTC)
    for offset in range(HORIZON_DAYS):
        day = local_now.date() + timedelta(days=offset)
        for lesson in calendar.day(day).lessons:
            if lesson['type'] == 'schedule' and lesson['schedule_item_id'] not in slots:
                continue
            start = lesson['start'].replace(tzinfo=local_now.tzinfo)
            if start.astimezone(UTC) < instant:
                continue
            subject = subjects.get(slots.get(lesson.get('schedule_item_id')) or lesson.get('subject_id'))
            score = relevance(query, lesson['title'], subject.name if subject else '',
                              lesson.get('room'), subject.teacher if subject else '')
            if score is None:
                continue
            details = f'{day:%d.%m.%Y} · {_time(lesson)}'
            if lesson.get('room'):
                details += f" · Ауд. {lesson['room']}"
            results.append({'title': lesson['title'], 'details': details, 'start': start,
                            'rank': (score, start.astimezone(UTC), len(results))})
    return rank_results(results)


def collect(db, user, query, local_now, group=None):
    normalized = normalize_query(query)
    if len(normalized.replace(' ', '')) < 2:
        return {}
    results = {}
    if group in (None, 'tasks'):
        results['tasks'] = search_tasks(db, user, normalized, local_now.replace(tzinfo=None))
    if group in (None, 'notes'):
        results['notes'] = search_notes(db, user, normalized)
    if group in (None, 'classes'):
        results['classes'] = search_classes(db, user, normalized, local_now)
    return results


def short(value, limit):
    """Bound escaped HTML in UTF-16 units, including emoji and entity expansion."""
    value = ' '.join(value.split())
    output, size = [], 0
    for char in value:
        encoded = escape(char, quote=False)
        units = len(encoded.encode('utf-16-le')) // 2
        if size + units > limit - 1:
            return ''.join(output) + '…'
        output.append(encoded)
        size += units
    return ''.join(output)


def navigation():
    return [[button('📌 Задачи', 'tasks'), button('📝 Заметка', 'note_start')],
            [button('📅 Расписание', 'week'), button('🔎 Искать ещё', 'search')],
            [button('← Главное меню', 'start')]]


def format_search_results(query, results, token, *, group=None, page=0):
    label = short(query, 120)
    if not any(results.values()):
        return (f'🔎 По запросу «{label}» ничего не найдено.\n\nПопробуй другое слово или более короткий запрос.',
                keyboard([button('🔎 Искать ещё', 'search')], [button('← Главное меню', 'start')]))
    lines, rows = [f'🔎 Результаты: «{label}»'], []
    for kind, items in results.items():
        if not items:
            continue
        start = page * PAGE_SIZE if group else 0
        lines.append('\n' + GROUPS[kind][0])
        for index, item in enumerate(items[start:start + PAGE_SIZE], start + 1):
            lines.append(f"{index}. {short(item['title'], 70)}")
            if item['details']:
                lines.append('   ' + short(item['details'], 140))
        if len(items) > PAGE_SIZE:
            shown = f'{start + 1}–{min(start + PAGE_SIZE, len(items))}' if page else str(min(PAGE_SIZE, len(items)))
            lines.append(f'Показано {shown} из {len(items)} {GROUPS[kind][1]}.')
        if page and group:
            rows.append([button('⬅️ Назад', f'search_page:{token}:{kind}:{page - 1}')])
        if start + PAGE_SIZE < len(items):
            name = {'tasks': '📌 Ещё задачи', 'notes': '📝 Ещё заметки', 'classes': '🎓 Ещё занятия'}[kind]
            rows.append([button(name, f'search_page:{token}:{kind}:{page + 1}')])
    return '\n'.join(lines), keyboard(*(rows + navigation()))


def waiting(db, telegram_user_id):
    state = db.get(TelegramState, f'search-flow:{telegram_user_id}')
    return bool(state and state.data)


def expired():
    return '⚠️ Поиск устарел.', keyboard([button('🔎 Новый поиск', 'search')])


def handle(db, user, *, telegram_user_id, action, argument, local_now, task_active=False):
    """Called after private/identity guards and notes, before intents/task parsing."""
    key = f'search-flow:{telegram_user_id}'
    state = db.get(TelegramState, key)
    pending = bool(state and state.data)
    prefix = PREFIX.fullmatch(argument.strip()) if action == 'text' else None
    cancel = action in {'cancel', 'add_task_cancel'} or (action == 'text' and argument.casefold() in {
        'отмена', 'отменить', 'cancel', '❌ отмена', '❌ отменить'})
    search_action = action == 'search' or action.startswith(('search_cancel:', 'search_page:'))
    if action == 'start' and pending:
        state.data = {}
        return None
    if not search_action and not prefix and not (pending and (action == 'text' or cancel)):
        return None
    if not user:
        return ('Сначала подключи Telegram в профиле Student Assistant.',
                keyboard([button('🔗 Подключить Telegram', 'connect')]))
    if task_active:
        if action == 'text' or cancel:
            return None
        return 'Сначала заверши действие с задачей или отмени его: /cancel', keyboard([button('❌ Отменить', 'add_task_cancel')])
    note = db.get(TelegramState, f'note-flow:{telegram_user_id}')
    if action == 'search' and note and note.data:
        return 'Сначала заверши заметку или отмени её: /cancel', keyboard([button('❌ Отмена', 'cancel')])
    if action.startswith('search_page:'):
        parts = action.split(':')
        snapshot = db.get(TelegramState, f'search-results:{telegram_user_id}')
        if (len(parts) != 4 or not snapshot or snapshot.expires_at <= utcnow()
                or snapshot.data.get('binding') != binding(user) or snapshot.data.get('token') != parts[1]
                or parts[2] not in GROUPS or not re.fullmatch(r'[0-9]{1,6}', parts[3])):
            return expired()
        query, group, page = snapshot.data['query'], parts[2], int(parts[3])
        results = collect(db, user, query, local_now, group)
        if page * PAGE_SIZE >= len(results[group]):
            return expired()
        return format_search_results(query, results, parts[1], group=group, page=page)
    if action.startswith('search_cancel:'):
        if not pending or state.data.get('token') != action.partition(':')[2]:
            return expired()
        cancel = True
    if cancel and pending:
        state.data = {}
        return '❌ Поиск отменён.', keyboard([button('🔎 Искать ещё', 'search')], [button('← Главное меню', 'start')])
    if action == 'search':
        state = state_row(db, key)
        state.data = {'state': 'waiting_for_search_query', 'token': secrets.token_hex(6), 'binding': binding(user)}
        state.expires_at = utcnow() + TTL
        return ('🔎 <b>Поиск</b>\n\nЧто найти?\n\nМожно искать задачи, заметки и занятия.\n\n'
                'Например:\n• практика по БД\n• английский\n• оконные функции',
                keyboard([button('❌ Отмена', f"search_cancel:{state.data['token']}")]))
    if pending and (state.expires_at <= utcnow() or state.data.get('binding') != binding(user)):
        state.data = {}
        return expired()
    if action == 'text':
        # A waiting flow consumes the literal message, before any explicit prefix.
        query = argument if pending else prefix[1]
        if len(normalize_query(query).replace(' ', '')) < 2 or len(query) > MAX_QUERY:
            if not pending:
                handle(db, user, telegram_user_id=telegram_user_id, action='search', argument='', local_now=local_now)
                state = db.get(TelegramState, key)
            message = '🔎 Напиши хотя бы 2 символа.' if len(query) <= MAX_QUERY else '🔎 Сократи запрос до 200 символов.'
            return message, keyboard([button('❌ Отмена', f"search_cancel:{state.data['token']}")])
        if pending:
            state.data = {}
        snapshot = state_row(db, f'search-results:{telegram_user_id}')
        token = secrets.token_hex(6)
        snapshot.data = {'query': query, 'token': token, 'binding': binding(user)}
        snapshot.expires_at = utcnow() + TTL
        return format_search_results(query, collect(db, user, query, local_now), token)
    return None
