from datetime import timedelta

from ..core.time import WEEKDAYS, current_time
from .task_schedule_links import get_task_anchor_datetime


NOTIFICATION_LIMIT = 8
SEARCH_DESCRIPTION_LIMIT = 110
ACADEMIC_EVENT_TYPE_LABELS = {
    'exam': 'Экзамен',
    'credit': 'Зачет',
    'consultation': 'Консультация',
    'resit': 'Пересдача',
    'changed_class': 'Разовая пара',
    'day_override': 'Особый день',
}


def _compact_text(value: str | None, fallback: str = '') -> str:
    compact = ' '.join((value or '').split())
    if not compact:
        return fallback
    if len(compact) <= SEARCH_DESCRIPTION_LIMIT:
        return compact
    return f'{compact[:SEARCH_DESCRIPTION_LIMIT - 1].rstrip()}…'


def _subject_name(item, fallback: str = 'Без предмета') -> str:
    subject = getattr(item, 'subject', None)
    return getattr(subject, 'name', None) or fallback


def _format_date_time(value) -> str:
    return value.strftime('%d.%m.%Y · %H:%M')


def _search_items(user) -> list[dict]:
    items = []

    for task in sorted(user.tasks, key=lambda item: (item.is_completed, item.title.lower())):
        subject_name = _subject_name(task)
        anchor = get_task_anchor_datetime(task)
        details = [subject_name]
        if anchor:
            details.append(f'до {_format_date_time(anchor)}')
        if task.description:
            details.append(_compact_text(task.description))
        items.append({
            'id': f'task-{task.id}',
            'type': 'task',
            'type_label': 'Задача',
            'title': task.title,
            'description': ' · '.join(details),
            'keywords': f'{task.title} {task.description or ""} {subject_name}',
            'href': f'/tasks?task={task.id}',
        })

    for subject in sorted(user.subjects, key=lambda item: item.name.lower()):
        details = [
            value
            for value in (
                subject.teacher,
                f'Аудитория {subject.room}' if subject.room else None,
                _compact_text(subject.notes) if subject.notes else None,
            )
            if value
        ]
        items.append({
            'id': f'subject-{subject.id}',
            'type': 'subject',
            'type_label': 'Предмет',
            'title': subject.name,
            'description': ' · '.join(details) or 'Учебный предмет',
            'keywords': f'{subject.name} {subject.teacher or ""} {subject.room or ""} {subject.notes or ""}',
            'href': f'/subjects#subject-card-{subject.id}',
        })

    for schedule_item in sorted(
        user.schedule_items,
        key=lambda item: (item.weekday, item.start_time, item.subject.name.lower()),
    ):
        details = (
            f'{WEEKDAYS[schedule_item.weekday]} · '
            f'{schedule_item.start_time.strftime("%H:%M")}–{schedule_item.end_time.strftime("%H:%M")}'
        )
        if schedule_item.room:
            details += f' · {schedule_item.room}'
        items.append({
            'id': f'class-{schedule_item.id}',
            'type': 'class',
            'type_label': 'Пара',
            'title': schedule_item.subject.name,
            'description': details,
            'keywords': (
                f'{schedule_item.subject.name} {schedule_item.lesson_type or ""} '
                f'{schedule_item.room or ""} {WEEKDAYS[schedule_item.weekday]}'
            ),
            'href': f'/schedule#schedule-row-{schedule_item.id}',
        })

    for event in sorted(user.academic_events, key=lambda item: (item.event_date, item.start_time or current_time().time())):
        event_label = ACADEMIC_EVENT_TYPE_LABELS.get(event.event_type, 'Событие')
        details = [event_label, event.event_date.strftime('%d.%m.%Y')]
        if event.start_time:
            details.append(event.start_time.strftime('%H:%M'))
        if event.room:
            details.append(event.room)
        items.append({
            'id': f'event-{event.id}',
            'type': 'event',
            'type_label': 'Событие',
            'title': event.title,
            'description': ' · '.join(details),
            'keywords': (
                f'{event.title} {event.description or ""} {_subject_name(event, "")} '
                f'{event_label} {event.room or ""}'
            ),
            'href': (
                f'/calendar?year={event.event_date.year}&month={event.event_date.month}'
                f'&selected={event.event_date.isoformat()}&view=week'
            ),
        })

    for note in sorted(user.notes, key=lambda item: item.created_at or current_time(), reverse=True):
        subject_name = _subject_name(note)
        items.append({
            'id': f'note-{note.id}',
            'type': 'note',
            'type_label': 'Заметка',
            'title': note.title,
            'description': _compact_text(note.content, subject_name),
            'keywords': f'{note.title} {note.content or ""} {subject_name} {note.link or ""}',
            'href': f'/notes?note={note.id}#note-card-{note.id}',
        })

    return items


def _task_notification(task, group: str, anchor=None) -> dict:
    anchor = anchor or get_task_anchor_datetime(task)
    if not anchor:
        time_label = 'Без срока'
    elif group == 'overdue':
        time_label = f'Просрочено · {anchor.strftime("%d.%m в %H:%M")}'
    elif group == 'today':
        time_label = f'Сегодня до {anchor.strftime("%H:%M")}'
    else:
        time_label = anchor.strftime('%d.%m в %H:%M')
    return {
        'id': f'task-{task.id}-{group}-{anchor.isoformat() if anchor else "undated"}',
        'kind': 'overdue' if group == 'overdue' else 'task',
        'title': task.title,
        'description': _subject_name(task),
        'time': time_label,
        'href': f'/tasks?task={task.id}',
    }


def _class_notification(schedule_item, day, day_label: str) -> dict:
    return {
        'id': f'class-{schedule_item.id}-{day.isoformat()}',
        'kind': 'class',
        'title': schedule_item.subject.name,
        'description': ' · '.join(
            value
            for value in (
                schedule_item.lesson_type or 'Занятие',
                f'Аудитория {schedule_item.room}' if schedule_item.room else None,
            )
            if value
        ),
        'time': f'{day_label}, {schedule_item.start_time.strftime("%H:%M")}–{schedule_item.end_time.strftime("%H:%M")}',
        'href': f'/schedule#schedule-row-{schedule_item.id}',
    }


def _event_notification(event) -> dict:
    event_label = ACADEMIC_EVENT_TYPE_LABELS.get(event.event_type, 'Событие')
    kind = 'change' if event.event_type in {'changed_class', 'day_override'} else 'exam'
    time_parts = [event.event_date.strftime('%d.%m')]
    if event.start_time:
        time_parts.append(event.start_time.strftime('%H:%M'))
    return {
        'id': f'event-{event.id}-{event.event_date.isoformat()}',
        'kind': kind,
        'title': event.title,
        'description': ' · '.join(
            value
            for value in (
                event_label,
                _subject_name(event, ''),
                event.room,
            )
            if value
        ),
        'time': ' · '.join(time_parts),
        'href': (
            f'/calendar?year={event.event_date.year}&month={event.event_date.month}'
            f'&selected={event.event_date.isoformat()}&view=week'
        ),
    }


def _notifications(user) -> dict[str, list[dict]]:
    now = current_time()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    soon_cutoff = today + timedelta(days=14)
    groups = {'today': [], 'soon': [], 'overdue': []}
    undated_tasks = []

    pending_tasks = sorted(
        (task for task in user.tasks if not task.is_completed),
        key=lambda task: get_task_anchor_datetime(task) or current_time().replace(year=9999),
    )
    for task in pending_tasks:
        anchor = get_task_anchor_datetime(task)
        if not anchor:
            undated_tasks.append(task)
        elif anchor < now:
            groups['overdue'].append(_task_notification(task, 'overdue', anchor))
        elif anchor.date() == today:
            groups['today'].append(_task_notification(task, 'today', anchor))
        elif anchor.date() <= today + timedelta(days=7):
            groups['soon'].append(_task_notification(task, 'soon', anchor))

    for schedule_item in sorted(user.schedule_items, key=lambda item: (item.weekday, item.start_time)):
        if schedule_item.weekday == today.weekday() and schedule_item.end_time >= now.time():
            groups['today'].append(_class_notification(schedule_item, today, 'Сегодня'))
        elif schedule_item.weekday == tomorrow.weekday():
            groups['soon'].append(_class_notification(schedule_item, tomorrow, 'Завтра'))

    for event in sorted(user.academic_events, key=lambda item: (item.event_date, item.start_time or now.time())):
        if event.event_date < today or event.event_date > soon_cutoff:
            continue
        target = 'today' if event.event_date == today else 'soon'
        groups[target].append(_event_notification(event))

    if not groups['soon']:
        groups['soon'].extend(_task_notification(task, 'soon') for task in undated_tasks[:3])

    for name in groups:
        groups[name] = groups[name][:NOTIFICATION_LIMIT]

    return groups


def build_navbar_payload(user) -> dict:
    if not user:
        return {'user_id': None, 'search': [], 'notifications': {'today': [], 'soon': [], 'overdue': []}}
    return {
        'user_id': user.id,
        'search': _search_items(user),
        'notifications': _notifications(user),
    }
