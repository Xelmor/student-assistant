from datetime import date, datetime, time, timedelta


def parse_scheduled_for_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def validate_schedule_link(schedule_item, scheduled_for_date: date | None):
    if schedule_item and scheduled_for_date and schedule_item.weekday != scheduled_for_date.weekday():
        raise ValueError('Дата занятия не совпадает с днем недели выбранной пары.')


def get_task_anchor_datetime(task) -> datetime | None:
    if getattr(task, 'deadline', None):
        return task.deadline

    scheduled_for_date = getattr(task, 'scheduled_for_date', None)
    if not scheduled_for_date:
        return None

    schedule_item = getattr(task, 'schedule_item', None)
    if schedule_item and getattr(schedule_item, 'start_time', None):
        return datetime.combine(scheduled_for_date, schedule_item.start_time)

    return datetime.combine(scheduled_for_date, time(hour=23, minute=59))


def get_task_calendar_event(task, now: datetime, fallback_subject_label: str = 'Без предмета') -> dict | None:
    anchor_datetime = get_task_anchor_datetime(task)
    scheduled_for_date = getattr(task, 'scheduled_for_date', None)

    if anchor_datetime is None and scheduled_for_date is None:
        return None

    schedule_item = getattr(task, 'schedule_item', None)
    subject_name = task.subject.name if getattr(task, 'subject', None) else fallback_subject_label
    if schedule_item and getattr(schedule_item, 'subject', None):
        subject_name = schedule_item.subject.name

    if scheduled_for_date and schedule_item:
        start_dt = datetime.combine(scheduled_for_date, schedule_item.start_time)
        end_dt = datetime.combine(scheduled_for_date, schedule_item.end_time)
        time_label = f"{schedule_item.start_time.strftime('%H:%M')} - {schedule_item.end_time.strftime('%H:%M')}"
        badge = 'К занятию'
        meta = schedule_item.lesson_type or subject_name
        room = schedule_item.room
        event_date = scheduled_for_date
    else:
        if scheduled_for_date and not getattr(task, 'deadline', None):
            start_dt = datetime.combine(scheduled_for_date, time(hour=12))
            end_dt = start_dt + timedelta(hours=1)
        else:
            start_dt = anchor_datetime
            end_dt = anchor_datetime + timedelta(hours=1)
        time_label = anchor_datetime.strftime('%H:%M') if getattr(task, 'deadline', None) else 'На день'
        badge = 'К дате' if scheduled_for_date else 'Дедлайн'
        meta = subject_name
        room = None
        event_date = scheduled_for_date or anchor_datetime.date()

    return {
        'date': event_date,
        'type': 'task',
        'title': task.title,
        'subject': subject_name,
        'start': start_dt,
        'end': end_dt,
        'time_label': time_label,
        'meta': meta,
        'badge': badge,
        'priority': task.priority,
        'is_completed': task.is_completed,
        'is_overdue': (not task.is_completed) and anchor_datetime < now,
        'description': task.description or '',
        'room': room,
        'task_id': task.id,
        'schedule_item_id': getattr(task, 'schedule_item_id', None),
        'scheduled_for_date': scheduled_for_date.isoformat() if scheduled_for_date else None,
    }
