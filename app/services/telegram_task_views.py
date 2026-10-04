"""Bounded task cards and versioned buttons shared by the bot and reminders."""
from datetime import datetime
from hashlib import sha256
from html import escape
import json

from ..models import Task, TelegramState
from .calendar_service import MONTH_NAMES_RU_GENITIVE
from .task_schedule_links import get_task_anchor_datetime
from .telegram_today import _task_rank
from .telegram_task_draft import button, keyboard


PAGE_SIZE = 1  # A Telegram keyboard can only sit below the entire message.


def revision(db, task):
    row = db.get(TelegramState, f'task-rev:{task.user_id}:{task.id}')
    values = {column.name: str(getattr(task, column.name)) for column in Task.__table__.columns}
    values['revision'] = (row.data if row else {}).get('version', 0)
    return sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]


def task_button(db, task, label, action):
    return button(label, f'{action}:{task.id}:{revision(db, task)}')


def date_label(value):
    if value is None:
        return 'Без дедлайна'
    return f'{value.day} {MONTH_NAMES_RU_GENITIVE[value.month]} {value.year}, {value:%H:%M}'


def stale():
    return ('⚠️ Эта кнопка уже неактуальна.\nОткрой свежий список задач.',
            keyboard([button('📌 Обновить список', 'tasks')]))


def card(task):
    lines = [f'📌 <b>{escape(task.title, quote=False)}</b>']
    if task.subject:
        lines.append('📚 ' + escape(task.subject.name, quote=False))
    anchor = get_task_anchor_datetime(task)
    if anchor:
        lines.append('📅 ' + date_label(anchor))
    lines.append({'high': '🔴 Высокий приоритет', 'medium': '🟡 Средний приоритет', 'low': '🟢 Низкий приоритет'}.get(task.priority, '🟡 Средний приоритет'))
    return '\n'.join(lines)


def active_tasks(db, user, now):
    tasks = db.query(Task).filter(Task.user_id == user.id, Task.is_completed.is_(False)).all()
    return sorted(tasks, key=lambda task: (_task_rank(task, now), get_task_anchor_datetime(task) or datetime.max, task.id))


def task_page(db, user, now, page=0):
    tasks = active_tasks(db, user, now)
    if page < 0 or (tasks and page >= len(tasks)) or (not tasks and page):
        text, markup = stale()
        return text, markup, []
    anchors = [get_task_anchor_datetime(task) for task in tasks]
    text = (f'📌 <b>Задачи</b>\n\nАктивных: {len(tasks)}\n'
            f'На сегодня: {sum(bool(anchor and anchor.date() == now.date()) for anchor in anchors)}\n'
            f'Просрочено: {sum(bool(anchor and anchor < now) for anchor in anchors)}')
    visible = tasks[page:page + PAGE_SIZE]
    rows = []
    if visible:
        task = visible[0]
        text += f'\n\n{card(task)}\n\nКарточка {page + 1} из {len(tasks)}'
        rows += [
            [task_button(db, task, '✅ Выполнено', 'task_done'), task_button(db, task, '⏰ Перенести', 'task_reschedule')],
            [task_button(db, task, '✏️ Изменить', 'task_edit')],
        ]
    else:
        text += '\n\nАктивных задач пока нет ✅'
    navigation = []
    if page:
        navigation.append(button('← Назад', f'tasks_page:{page - 1}'))
    if page + 1 < len(tasks):
        navigation.append(button('Вперёд →', f'tasks_page:{page + 1}'))
    if navigation:
        rows.append(navigation)
    rows.append([button('➕ Добавить задачу', 'add_task_start')])
    return text, keyboard(*rows), visible


def after_done(db, task, remaining):
    return (f'✅ <b>Задача выполнена</b>\n\n{escape(task.title, quote=False)}\n\nОсталось активных задач: {remaining}',
            keyboard([task_button(db, task, '↩️ Вернуть', 'task_restore')], [button('📌 Все задачи', 'tasks')]))


def after_restore(db, task):
    return (f'↩️ <b>Задача снова активна</b>\n\n{escape(task.title, quote=False)}',
            keyboard([task_button(db, task, '✅ Выполнено', 'task_done')], [button('📌 Все задачи', 'tasks')]))


def after_update(db, task, heading='✅ Дедлайн перенесён'):
    return (f'<b>{heading}</b>\n\n{card(task)}', keyboard(
        [task_button(db, task, '✅ Выполнено', 'task_done')],
        [task_button(db, task, '✏️ Изменить', 'task_edit')],
        [button('📌 Все задачи', 'tasks')],
    ))
