"""Owned, explicit task mutations. The existing Telegram transaction owns commit."""
from datetime import datetime, time, timedelta
from html import escape

from ..models import Task
from .task_completion import complete_task
from .telegram_state import state_row
from .recurring_tasks import recurrence_requires_deadline
from .telegram_task_parser import parse_task
from .telegram_task_draft import button, keyboard
from . import telegram_task_views as views


RESCHEDULE = 'task_reschedule_choose'
RESCHEDULE_DATE = 'task_reschedule_date'
RESCHEDULE_CONFIRM = 'task_reschedule_confirm'
RESCHEDULE_STEPS = (RESCHEDULE, RESCHEDULE_DATE, RESCHEDULE_CONFIRM)


class StaleTask(Exception):
    pass


def owned_task(db, user, task_id, expected=None):
    # Serialize writes on SQLite, then lock the Task row on PostgreSQL. Use a
    # separate state key: the scheduler locks its key before the User row, while
    # Telegram has already updated User, so sharing that key could deadlock.
    state_row(db, f'task-action-lock:{user.id}:{task_id}')
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).populate_existing().with_for_update().first()
    if not task or (expected is not None and views.revision(db, task) != expected):
        raise StaleTask()
    return task


def mark_changed(db, task):
    row = state_row(db, f'task-rev:{task.user_id}:{task.id}')
    row.data = {'version': row.data.get('version', 0) + 1}
    # A revision is durable metadata, not an expiring action draft.
    row.expires_at = datetime.max
    db.flush()


def set_deadline(task, deadline):
    if task.deadline != deadline:
        task.deadline = deadline
        # A previous lesson/date placement would otherwise pin the calendar
        # entry to its old day despite an explicit deadline change.
        task.scheduled_for_date = None
        task.schedule_item_id = None


def handle_action(db, user, action, now):
    parts = action.split(':')
    if len(parts) != 3 or not parts[1].isdigit() or len(parts[1]) > 18:
        raise StaleTask()
    kind, task_id, expected = parts
    task = owned_task(db, user, int(task_id), expected)
    if kind == 'task_done' and not task.is_completed:
        complete_task(db, task)
        mark_changed(db, task)
        remaining = db.query(Task).filter(Task.user_id == user.id, Task.is_completed.is_(False)).count()
        return views.after_done(db, task, remaining)
    if kind == 'task_restore' and task.is_completed:
        task.is_completed, task.completed_at = False, None
        mark_changed(db, task)
        return views.after_restore(db, task)
    if kind in {'task_reschedule', 'task_edit'} and not task.is_completed:
        return task
    raise StaleTask()


def render_reschedule(dialog, now):
    title = escape(dialog.title, quote=False)
    cancel = [button('❌ Отмена', 'add_task_cancel')]
    if dialog.step == RESCHEDULE_DATE:
        return ('Введите новую дату и время.\n\nНапример:\n02.10 18:30\nзавтра 20:00\nв пятницу 17:00',
                keyboard([button('← Назад', 'add_task_reschedule_back')], cancel))
    if dialog.step == RESCHEDULE_CONFIRM:
        return (f'⏰ <b>Новый дедлайн</b>\n\n{title}\nБыло: {views.date_label(datetime.fromisoformat(dialog.original_deadline) if dialog.original_deadline else None)}\nСтанет: {views.date_label(dialog.deadline)}',
                keyboard([button('✅ Перенести', 'add_task_reschedule_save')],
                         [button('← Назад', 'add_task_reschedule_back')], cancel))
    rows = []
    if now.time() < time(20):
        rows.append([button('Сегодня, 20:00', 'add_task_reschedule_today')])
    rows += [[button('Завтра', 'add_task_reschedule_tomorrow')],
             [button('+3 дня', 'add_task_reschedule_3'), button('+7 дней', 'add_task_reschedule_7')],
             [button('📅 Другая дата', 'add_task_reschedule_custom')], cancel]
    return f'⏰ Перенести «{title}»\n\nНа когда?', keyboard(*rows)


def reschedule_action(db, user, dialog, action, argument, now):
    task = owned_task(db, user, dialog.edit_task_id, dialog.task_revision)
    if task.is_completed:
        raise StaleTask()
    if action == 'add_task_reschedule_back':
        dialog.step = RESCHEDULE
    elif action == 'add_task_reschedule_custom':
        dialog.step = RESCHEDULE_DATE
    elif action == 'text' and dialog.step == RESCHEDULE_DATE:
        try:
            parsed = parse_task('Задача ' + argument, now=now)
        except ValueError:
            parsed = None
        if not parsed or not parsed.deadline or parsed.warning:
            text, markup = render_reschedule(dialog, now)
            warning = parsed.warning if parsed and parsed.warning else 'Не получилось распознать дату.'
            return (f'⚠️ {warning}\n\n{text}', markup), False
        dialog.deadline, dialog.step = parsed.deadline, RESCHEDULE_CONFIRM
    elif action in {'add_task_reschedule_today', 'add_task_reschedule_tomorrow', 'add_task_reschedule_3', 'add_task_reschedule_7'} and dialog.step == RESCHEDULE:
        old = task.deadline
        clock = old.time() if old else time(23, 59)
        if action.endswith('_today'):
            candidate = datetime.combine(now.date(), time(20))
        elif action.endswith('_tomorrow'):
            candidate = datetime.combine(now.date() + timedelta(days=1), clock)
        else:
            delta = int(action.rsplit('_', 1)[1])
            candidate = datetime.combine(old.date() if old else now.date(), clock) + timedelta(days=delta)
        if candidate <= now:
            text, markup = render_reschedule(dialog, now)
            return (f'⚠️ Эта дата уже прошла. Выбери другую.\n\n{text}', markup), False
        dialog.deadline, dialog.step = candidate, RESCHEDULE_CONFIRM
    elif action == 'add_task_reschedule_save' and dialog.step == RESCHEDULE_CONFIRM:
        if not dialog.deadline or dialog.deadline <= now:
            dialog.step = RESCHEDULE
            text, markup = render_reschedule(dialog, now)
            return (f'⚠️ Это время уже прошло. Выбери другую дату.\n\n{text}', markup), False
        set_deadline(task, dialog.deadline)
        mark_changed(db, task)
        return views.after_update(db, task), True
    return render_reschedule(dialog, now), False


def save_edit(db, user, dialog, *, title, subject_id):
    task = owned_task(db, user, dialog.edit_task_id, dialog.task_revision)
    if task.is_completed:
        raise StaleTask()
    if recurrence_requires_deadline(task.recurrence_type) and dialog.deadline is None:
        raise ValueError('Для повторяющейся задачи нужно указать дедлайн.')
    task.title, task.subject_id, task.priority = title, subject_id, dialog.priority
    set_deadline(task, dialog.deadline)
    mark_changed(db, task)
    return task
