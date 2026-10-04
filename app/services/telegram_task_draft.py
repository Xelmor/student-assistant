"""Presentation and transitions for parsed drafts inside the existing dialog."""
from datetime import timedelta
from html import escape
import secrets

from .calendar_service import MONTH_NAMES_RU_GENITIVE


def button(text, action):
    return {'text': text, 'callback_data': action}


def keyboard(*rows):
    return {'inline_keyboard': list(rows)}


def phrase_prompt():
    return ('📝 <b>Новая задача</b>\n\nОпиши её одним сообщением.\n\n'
            'Например:\n• сдать практику по БД завтра в 18\n'
            '• выучить слова к пятнице\n• сделать Python на вторник')


def deadline_label(deadline, now, *, show_time=True):
    if deadline is None:
        return 'Без дедлайна'
    delta = (deadline.date() - now.date()).days
    if delta in {0, 1, 2}:
        day = {0: 'Сегодня', 1: 'Завтра', 2: 'Послезавтра'}[delta]
        return f'{day}, {deadline:%H:%M}' if show_time else day
    weekdays = ('Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье')
    day = f'{weekdays[deadline.weekday()]}, {deadline.day} {MONTH_NAMES_RU_GENITIVE[deadline.month]}'
    if deadline.year != now.year:
        day += f' {deadline.year}'
    return f'{day} · {deadline:%H:%M}' if show_time else day


def details(draft, now, *, priority=True):
    lines = [f'<b>{escape(draft.title or "", quote=False)}</b>', '']
    if draft.subject_name:
        lines.append('📚 ' + escape(draft.subject_name, quote=False))
    elif priority:
        lines.append('📚 Без предмета')
    lines.append('📅 ' + deadline_label(draft.deadline, now, show_time=draft.time_explicit))
    if priority:
        lines.append({'high': '🔴 Высокий приоритет', 'medium': '🟡 Средний приоритет', 'low': '🟢 Низкий приоритет'}[draft.priority])
    if draft.subject_warning:
        lines.append('⚠️ Предмет не найден, задача будет без предмета.')
    return '\n'.join(lines)


def current_warning(draft, now):
    if draft.warning:
        return draft.warning
    if getattr(draft, 'edit_task_id', None) and (draft.deadline.isoformat() if draft.deadline else None) == draft.original_deadline:
        return None
    if draft.deadline and draft.deadline < now.replace(tzinfo=None):
        if draft.deadline.date() == now.date():
            return 'Это время сегодня уже прошло.'
        return 'Эта дата уже прошла. Измени дедлайн.'
    return None


def render_draft(draft, now, subjects):
    cancel = [button('❌ Отмена', 'add_task_cancel')]
    warning = current_warning(draft, now)
    if warning:
        rows = []
        if draft.deadline and draft.deadline.date() == now.date() and draft.deadline < now.replace(tzinfo=None):
            rows.append([button(f'📅 Завтра в {draft.deadline:%H:%M}', 'add_task_draft_tomorrow')])
        rows.extend([[button('✏️ Изменить', 'add_task_quick_customize')], cancel])
        return f'⚠️ {warning}\n\n{details(draft, now)}', keyboard(*rows)
    if draft.subject_candidates:
        rows = [[button(name, f'add_task_draft_subject:{sid}')] for sid, name in subjects if sid in draft.subject_candidates]
        rows.extend([[button('Без предмета', 'add_task_draft_subject:none')], cancel])
        return f'📚 Какой предмет?\nПодходит несколько предметов.\n\n{escape(draft.title, quote=False)}', keyboard(*rows)
    editing_task = getattr(draft, 'edit_task_id', None) is not None
    heading = '✏️ <b>Изменить задачу</b>' if editing_task else '📝 <b>Новая задача</b>'
    question = 'Сохранить изменения?' if editing_task else 'Всё верно?'
    label = '✅ Сохранить' if editing_task else '✅ Создать'
    return (
        f'{heading}\n\n{details(draft, now)}\n\n{question}',
        keyboard([button(label, 'add_task_quick_create'), button('✏️ Изменить', 'add_task_quick_customize')], cancel),
    )


def parsed_success(draft, now):
    return (
        f'✅ <b>Задача добавлена</b>\n\n{details(draft, now, priority=False)}',
        keyboard([button('📌 Все задачи', 'tasks'), button('➕ Ещё задачу', 'add_task_start')]),
    )


def populate_draft(dialog, parsed, subjects):
    dialog.natural = True
    dialog.awaiting_phrase = False
    dialog.time_explicit = parsed.time_explicit
    dialog.title, dialog.deadline, dialog.priority = parsed.title, parsed.deadline, parsed.priority
    dialog.warning = parsed.warning
    dialog.subject_candidates = list(parsed.subject_ids) if len(parsed.subject_ids) > 1 else []
    dialog.subject_title = parsed.subject_title
    if len(parsed.subject_ids) == 1:
        dialog.subject_id = parsed.subject_ids[0]
        dialog.subject_name = dict(subjects)[dialog.subject_id]
    return dialog


def edit_prefill(dialog, text, markup, now):
    """Decorate the existing editor; no parallel editing or persistence engine."""
    if not dialog.natural or not dialog.editing:
        return text, markup
    field = {
        'add_task_waiting_title': dialog.title,
        'add_task_waiting_deadline': deadline_label(dialog.deadline, now, show_time=dialog.time_explicit),
        'add_task_waiting_subject': dialog.subject_name or 'Без предмета',
        'add_task_waiting_priority': {'high': 'Высокий', 'medium': 'Средний', 'low': 'Низкий'}[dialog.priority],
    }.get(dialog.step)
    if field is not None:
        text += f'\n\nСейчас: {escape(field, quote=False)}'
        markup['inline_keyboard'].insert(0, [button('Оставить как есть', 'add_task_keep')])
    return text, markup


def tomorrow_at_same_time(dialog, now):
    if not dialog.deadline or dialog.deadline.date() != now.date() or dialog.deadline >= now.replace(tzinfo=None):
        return False
    dialog.deadline += timedelta(days=1)
    dialog.warning = None
    return True


def apply_action(dialog, action, now, subjects):
    """Handle parsed-draft choices; field editing stays in the existing flow."""
    if action == 'add_task_keep' and dialog.editing:
        steps = ['add_task_waiting_title', 'add_task_waiting_deadline',
                 'add_task_waiting_subject', 'add_task_waiting_priority', 'add_task_confirm']
        if dialog.step in steps[:-1]:
            dialog.step = steps[steps.index(dialog.step) + 1]
            return True
    if action == 'add_task_draft_tomorrow':
        if dialog.step in {'add_task_quick_confirm', 'add_task_confirm'}:
            tomorrow_at_same_time(dialog, now)
            dialog.generation = secrets.token_hex(4)
        return True
    if action.startswith('add_task_draft_subject:'):
        value = action.partition(':')[2]
        if dialog.subject_candidates:
            sid = int(value) if value.isdigit() else None
            name = dict(subjects).get(sid) if sid in dialog.subject_candidates else None
            if name or value == 'none':
                dialog.subject_id = sid if name else None
                dialog.subject_name = name
                if name and dialog.subject_title:
                    dialog.title = dialog.subject_title
                dialog.subject_candidates = []
                dialog.generation = secrets.token_hex(4)
        return True
    if action.startswith('add_task_deadline_'):
        dialog.warning = None
    return False
