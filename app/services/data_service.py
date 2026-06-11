import csv
import io
import json
import zipfile
from datetime import date, datetime
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from ..models import AcademicEvent, Note, ScheduleItem, Subject, Task, User
from ..core.time import current_time
from ..core.validation import (
    normalize_bounded_text,
    normalize_choice,
    normalize_external_url,
    normalize_hex_color,
)
from ..web.dependencies import SCHEDULE_UNIT_OPTIONS

MAX_IMPORT_RECORDS_PER_COLLECTION = 5000
MAX_IMPORT_TOTAL_RECORDS = 10000
CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
TASK_LEVELS = {'low', 'medium', 'high'}
TASK_RECURRENCE_TYPES = {'none', 'daily', 'weekly', 'custom_days'}
ACADEMIC_EVENT_TYPES = {
    'exam',
    'credit',
    'consultation',
    'resit',
    'changed_class',
    'day_override',
}


def serialize_datetime(value):
    if not value:
        return None
    return value.isoformat()


def serialize_time(value):
    if not value:
        return None
    return value.strftime('%H:%M:%S')


def parse_datetime_value(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError('Дата и время в файле импорта должны быть строкой.')
    return datetime.fromisoformat(value)


def parse_date_value(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError('Дата в файле импорта должна быть строкой.')
    return date.fromisoformat(value)


def parse_time_value(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError('Время в файле импорта должно быть строкой.')
    return datetime.strptime(value, '%H:%M:%S').time()


def parse_import_boolean(value, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f'Поле {label} должно быть логическим значением.')


def parse_import_recurrence(task_payload: dict) -> tuple[str, int | None]:
    recurrence_type = normalize_choice(
        task_payload.get('recurrence_type') or 'none',
        label='Тип повтора задачи',
        allowed=TASK_RECURRENCE_TYPES,
    )
    if recurrence_type != 'custom_days':
        return recurrence_type, None
    try:
        interval = int(task_payload.get('recurrence_interval_days'))
    except (TypeError, ValueError) as error:
        raise ValueError('Интервал повторения задачи должен быть целым числом.') from error
    if not 2 <= interval <= 365:
        raise ValueError('Интервал повторения задачи должен быть от 2 до 365 дней.')
    return recurrence_type, interval


def build_user_export_payload(user: User, db: Session):
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.id.asc()).all()
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.id.asc()).all()
    schedule_items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(ScheduleItem.id.asc()).all()
    academic_events = db.query(AcademicEvent).filter(AcademicEvent.user_id == user.id).order_by(AcademicEvent.id.asc()).all()
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.id.asc()).all()

    return {
        'version': 1,
        'exported_at': current_time().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
            'group_name': user.group_name,
            'course': user.course,
            'schedule_unit': user.schedule_unit,
            'last_study_day': user.last_study_day.isoformat() if user.last_study_day else None,
        },
        'data': {
            'subjects': [
                {
                    'id': subject.id,
                    'name': subject.name,
                    'teacher': subject.teacher,
                    'room': subject.room,
                    'color': subject.color,
                    'notes': subject.notes,
                }
                for subject in subjects
            ],
            'tasks': [
                {
                    'id': task.id,
                    'subject_id': task.subject_id,
                    'title': task.title,
                    'description': task.description,
                    'deadline': serialize_datetime(task.deadline),
                    'scheduled_for_date': task.scheduled_for_date.isoformat() if task.scheduled_for_date else None,
                    'schedule_item_id': task.schedule_item_id,
                    'priority': task.priority,
                    'difficulty': task.difficulty,
                    'is_completed': task.is_completed,
                    'recurrence_group_id': task.recurrence_group_id,
                    'recurrence_type': task.recurrence_type,
                    'recurrence_interval_days': task.recurrence_interval_days,
                    'created_at': serialize_datetime(task.created_at),
                }
                for task in tasks
            ],
            'schedule_items': [
                {
                    'id': item.id,
                    'subject_id': item.subject_id,
                    'weekday': item.weekday,
                    'start_time': serialize_time(item.start_time),
                    'end_time': serialize_time(item.end_time),
                    'lesson_type': item.lesson_type,
                    'room': item.room,
                }
                for item in schedule_items
            ],
            'academic_events': [
                {
                    'id': event.id,
                    'subject_id': event.subject_id,
                    'title': event.title,
                    'event_type': event.event_type,
                    'event_date': event.event_date.isoformat() if event.event_date else None,
                    'start_time': serialize_time(event.start_time),
                    'end_time': serialize_time(event.end_time),
                    'room': event.room,
                    'description': event.description,
                    'created_at': serialize_datetime(event.created_at),
                }
                for event in academic_events
            ],
            'notes': [
                {
                    'id': note.id,
                    'subject_id': note.subject_id,
                    'title': note.title,
                    'content': note.content,
                    'link': note.link,
                    'created_at': serialize_datetime(note.created_at),
                }
                for note in notes
            ],
        },
    }


def build_csv_export_archive(payload):
    archive_buffer = io.BytesIO()

    csv_specs = {
        'subjects.csv': (
            ['id', 'name', 'teacher', 'room', 'color', 'notes'],
            payload['data']['subjects'],
        ),
        'tasks.csv': (
            [
                'id',
                'subject_id',
                'title',
                'description',
                'deadline',
                'scheduled_for_date',
                'schedule_item_id',
                'priority',
                'difficulty',
                'is_completed',
                'recurrence_group_id',
                'recurrence_type',
                'recurrence_interval_days',
                'created_at',
            ],
            payload['data']['tasks'],
        ),
        'schedule_items.csv': (
            ['id', 'subject_id', 'weekday', 'start_time', 'end_time', 'lesson_type', 'room'],
            payload['data']['schedule_items'],
        ),
        'academic_events.csv': (
            ['id', 'subject_id', 'title', 'event_type', 'event_date', 'start_time', 'end_time', 'room', 'description', 'created_at'],
            payload['data'].get('academic_events', []),
        ),
        'notes.csv': (
            ['id', 'subject_id', 'title', 'content', 'link', 'created_at'],
            payload['data']['notes'],
        ),
    }

    with zipfile.ZipFile(archive_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            'export_meta.json',
            json.dumps(
                {
                    'version': payload['version'],
                    'exported_at': payload['exported_at'],
                    'user': payload['user'],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

        for filename, (fieldnames, rows) in csv_specs.items():
            text_buffer = io.StringIO()
            writer = csv.DictWriter(text_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        field: neutralize_csv_formula(row.get(field))
                        for field in fieldnames
                    }
                )
            archive.writestr(filename, text_buffer.getvalue().encode('utf-8-sig'))

    archive_buffer.seek(0)
    return archive_buffer


def neutralize_csv_formula(value):
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(CSV_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def build_download_headers(filename: str):
    return {
        'Content-Disposition': f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote_plus(filename)}',
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    }


def import_user_export_payload(user: User, payload, import_mode: str, db: Session):
    if not isinstance(payload, dict):
        raise ValueError('Корневой элемент файла импорта должен быть JSON-объектом.')

    data = payload.get('data')
    if not isinstance(data, dict):
        raise ValueError('В файле нет блока data с данными для импорта.')

    user_payload = payload.get('user', {})
    if isinstance(user_payload, dict):
        imported_schedule_unit = user_payload.get('schedule_unit')
        if imported_schedule_unit in SCHEDULE_UNIT_OPTIONS:
            user.schedule_unit = imported_schedule_unit
        user.last_study_day = parse_date_value(user_payload.get('last_study_day'))

    subjects_payload = data.get('subjects', [])
    tasks_payload = data.get('tasks', [])
    schedule_payload = data.get('schedule_items', [])
    academic_events_payload = data.get('academic_events', [])
    notes_payload = data.get('notes', [])

    for collection, label in [
        (subjects_payload, 'subjects'),
        (tasks_payload, 'tasks'),
        (schedule_payload, 'schedule_items'),
        (academic_events_payload, 'academic_events'),
        (notes_payload, 'notes'),
    ]:
        if not isinstance(collection, list):
            raise ValueError(f'Поле {label} должно быть списком.')
        if len(collection) > MAX_IMPORT_RECORDS_PER_COLLECTION:
            raise ValueError(
                f'Поле {label} содержит больше {MAX_IMPORT_RECORDS_PER_COLLECTION} записей.'
            )
        if any(not isinstance(item, dict) for item in collection):
            raise ValueError(f'Каждая запись в поле {label} должна быть JSON-объектом.')

    total_records = sum(
        len(collection)
        for collection in (
            subjects_payload,
            tasks_payload,
            schedule_payload,
            academic_events_payload,
            notes_payload,
        )
    )
    if total_records > MAX_IMPORT_TOTAL_RECORDS:
        raise ValueError(
            f'Файл содержит больше {MAX_IMPORT_TOTAL_RECORDS} записей суммарно.'
        )

    subject_id_map = {}

    if import_mode == 'replace':
        db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
        db.query(Note).filter(Note.user_id == user.id).delete(synchronize_session=False)
        db.query(AcademicEvent).filter(AcademicEvent.user_id == user.id).delete(synchronize_session=False)
        db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).delete(synchronize_session=False)
        db.query(Subject).filter(Subject.user_id == user.id).delete(synchronize_session=False)
        db.flush()

    for subject_payload in subjects_payload:
        subject_name = (
            normalize_bounded_text(
                subject_payload.get('name') or 'Без названия',
                label='Название предмета',
                max_length=100,
                required=True,
            )
            or 'Без названия'
        )
        subject = Subject(
            user_id=user.id,
            name=subject_name,
            teacher=normalize_bounded_text(
                subject_payload.get('teacher'),
                label='Преподаватель',
                max_length=100,
            ),
            room=normalize_bounded_text(
                subject_payload.get('room'),
                label='Аудитория',
                max_length=50,
            ),
            color=normalize_hex_color(subject_payload.get('color'), default='#0d6efd'),
            notes=normalize_bounded_text(
                subject_payload.get('notes'),
                label='Заметка предмета',
                max_length=5000,
            ),
        )
        db.add(subject)
        db.flush()
        original_subject_id = subject_payload.get('id')
        if original_subject_id is not None:
            subject_id_map[original_subject_id] = subject.id

    task_id_map = {}
    imported_task_groups = []

    for task_payload in tasks_payload:
        recurrence_type, recurrence_interval_days = parse_import_recurrence(task_payload)
        task = Task(
            user_id=user.id,
            subject_id=subject_id_map.get(task_payload.get('subject_id')),
            title=(
                normalize_bounded_text(
                    task_payload.get('title') or 'Без названия',
                    label='Название задачи',
                    max_length=150,
                    required=True,
                )
                or 'Без названия'
            ),
            description=normalize_bounded_text(
                task_payload.get('description'),
                label='Описание задачи',
                max_length=5000,
            ),
            deadline=parse_datetime_value(task_payload.get('deadline')),
            scheduled_for_date=parse_date_value(task_payload.get('scheduled_for_date')),
            schedule_item_id=None,
            priority=normalize_choice(
                task_payload.get('priority') or 'medium',
                label='Приоритет задачи',
                allowed=TASK_LEVELS,
            ),
            difficulty=normalize_choice(
                task_payload.get('difficulty') or 'medium',
                label='Сложность задачи',
                allowed=TASK_LEVELS,
            ),
            is_completed=parse_import_boolean(
                task_payload.get('is_completed', False),
                label='is_completed',
            ),
            recurrence_group_id=None,
            recurrence_type=recurrence_type,
            recurrence_interval_days=recurrence_interval_days,
            created_at=parse_datetime_value(task_payload.get('created_at')) or current_time(),
        )
        db.add(task)
        db.flush()

        original_task_id = task_payload.get('id')
        if original_task_id is not None:
            task_id_map[original_task_id] = task.id
        imported_task_groups.append((task, task_payload.get('recurrence_group_id')))

    for task, original_group_id in imported_task_groups:
        if task.recurrence_type == 'none':
            continue
        task.recurrence_group_id = task_id_map.get(original_group_id, task.id)

    schedule_id_map = {}

    for schedule_payload_item in schedule_payload:
        mapped_subject_id = subject_id_map.get(schedule_payload_item.get('subject_id'))
        if not mapped_subject_id:
            continue

        try:
            weekday = int(schedule_payload_item.get('weekday', 0))
        except (TypeError, ValueError) as error:
            raise ValueError('День недели в расписании должен быть целым числом.') from error
        if not 0 <= weekday <= 6:
            raise ValueError('День недели в расписании должен быть от 0 до 6.')
        start_time = parse_time_value(schedule_payload_item.get('start_time'))
        end_time = parse_time_value(schedule_payload_item.get('end_time'))
        start_time = start_time or datetime.strptime('09:00:00', '%H:%M:%S').time()
        end_time = end_time or datetime.strptime('10:00:00', '%H:%M:%S').time()
        if start_time >= end_time:
            raise ValueError('Время окончания занятия должно быть позже времени начала.')

        schedule_item = ScheduleItem(
            user_id=user.id,
            subject_id=mapped_subject_id,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            lesson_type=normalize_bounded_text(
                schedule_payload_item.get('lesson_type'),
                label='Тип занятия',
                max_length=50,
            ),
            room=normalize_bounded_text(
                schedule_payload_item.get('room'),
                label='Аудитория',
                max_length=50,
            ),
        )
        db.add(schedule_item)
        db.flush()

        original_schedule_item_id = schedule_payload_item.get('id')
        if original_schedule_item_id is not None:
            schedule_id_map[original_schedule_item_id] = schedule_item.id

    for task, task_payload in zip([group[0] for group in imported_task_groups], tasks_payload):
        original_schedule_item_id = task_payload.get('schedule_item_id')
        if original_schedule_item_id is not None:
            task.schedule_item_id = schedule_id_map.get(original_schedule_item_id)

    for event_payload in academic_events_payload:
        event_date = parse_date_value(event_payload.get('event_date'))
        if not event_date:
            continue

        db.add(
            AcademicEvent(
                user_id=user.id,
                subject_id=subject_id_map.get(event_payload.get('subject_id')),
                title=(
                    normalize_bounded_text(
                        event_payload.get('title') or 'Событие сессии',
                        label='Название события',
                        max_length=150,
                        required=True,
                    )
                    or 'Событие сессии'
                ),
                event_type=normalize_choice(
                    event_payload.get('event_type') or 'exam',
                    label='Тип события',
                    allowed=ACADEMIC_EVENT_TYPES,
                ),
                event_date=event_date,
                start_time=parse_time_value(event_payload.get('start_time')),
                end_time=parse_time_value(event_payload.get('end_time')),
                room=normalize_bounded_text(
                    event_payload.get('room'),
                    label='Аудитория события',
                    max_length=50,
                ),
                description=normalize_bounded_text(
                    event_payload.get('description'),
                    label='Описание события',
                    max_length=5000,
                ),
                created_at=parse_datetime_value(event_payload.get('created_at')) or current_time(),
            )
        )

    for note_payload in notes_payload:
        try:
            normalized_link = normalize_external_url(note_payload.get('link'))
        except ValueError as error:
            raise ValueError(f'Заметка содержит небезопасную ссылку: {error}') from error
        note = Note(
            user_id=user.id,
            subject_id=subject_id_map.get(note_payload.get('subject_id')),
            title=(
                normalize_bounded_text(
                    note_payload.get('title') or 'Без названия',
                    label='Заголовок заметки',
                    max_length=150,
                    required=True,
                )
                or 'Без названия'
            ),
            content=normalize_bounded_text(
                note_payload.get('content'),
                label='Текст заметки',
                max_length=10000,
            ),
            link=normalized_link,
            created_at=parse_datetime_value(note_payload.get('created_at')) or current_time(),
        )
        db.add(note)
