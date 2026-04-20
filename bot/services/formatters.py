from __future__ import annotations

from datetime import datetime


def format_datetime(value: str | None) -> str:
    if not value:
        return 'без дедлайна'
    parsed = datetime.fromisoformat(value)
    return parsed.strftime('%d.%m %H:%M')


def format_subjects(subjects: list[dict]) -> str:
    if not subjects:
        return 'У тебя пока нет предметов.'
    lines = ['Твои предметы:']
    for index, subject in enumerate(subjects, start=1):
        suffix = f" · {subject['teacher']}" if subject.get('teacher') else ''
        lines.append(f'{index}. {subject["name"]}{suffix}')
    return '\n'.join(lines)


def format_tasks(tasks: list[dict], title: str) -> str:
    if not tasks:
        return f'{title}\n\nСписок пуст.'
    lines = [title]
    for index, task in enumerate(tasks, start=1):
        subject = f" · {task['subject_name']}" if task.get('subject_name') else ''
        deadline = format_datetime(task.get('deadline'))
        lines.append(f'{index}. {task["title"]}{subject}\nДедлайн: {deadline}')
    return '\n\n'.join(lines)


def format_notes(notes: list[dict]) -> str:
    if not notes:
        return 'Заметок пока нет.'
    lines = ['Последние заметки:']
    for index, note in enumerate(notes, start=1):
        preview = (note.get('content') or '').strip().replace('\n', ' ')
        if len(preview) > 80:
            preview = preview[:77] + '...'
        subject = f" · {note['subject_name']}" if note.get('subject_name') else ''
        lines.append(f'{index}. {note["title"]}{subject}')
        if preview:
            lines.append(preview)
    return '\n'.join(lines)


def format_schedule(payload: dict, *, empty_text: str) -> str:
    schedule = payload.get('schedule', {})
    if not schedule:
        return empty_text
    lines: list[str] = []
    for weekday, items in schedule.items():
        lines.append(weekday)
        for item in items:
            lesson_type = f" ({item['lesson_type']})" if item.get('lesson_type') else ''
            room = f", ауд. {item['room']}" if item.get('room') else ''
            lines.append(
                f"{item['start_time']}-{item['end_time']} · {item['subject_name']}{lesson_type}{room}"
            )
        lines.append('')
    return '\n'.join(line for line in lines if line is not None).strip()


def format_reminders(settings: dict) -> str:
    state = 'включены' if settings['notifications_enabled'] else 'выключены'
    deadlines = 'включены' if settings['deadline_reminders_enabled'] else 'выключены'
    schedule = 'включены' if settings['schedule_reminders_enabled'] else 'выключены'
    return (
        'Настройки напоминаний:\n'
        f'Общие уведомления: {state}\n'
        f'Напоминания о дедлайнах: {deadlines}\n'
        f'Напоминания о парах: {schedule}'
    )
