import csv
import io
import json
import zipfile
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from ..models import Note, ScheduleItem, Subject, Task, User
from ..web.dependencies import SCHEDULE_UNIT_OPTIONS


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
    return datetime.fromisoformat(value)


def parse_time_value(value):
    if not value:
        return None
    return datetime.strptime(value, '%H:%M:%S').time()


def build_user_export_payload(user: User, db: Session):
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.id.asc()).all()
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.id.asc()).all()
    schedule_items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(ScheduleItem.id.asc()).all()
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.id.asc()).all()

    return {
        'version': 1,
        'exported_at': datetime.utcnow().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
            'group_name': user.group_name,
            'course': user.course,
            'schedule_unit': user.schedule_unit,
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
                    'priority': task.priority,
                    'difficulty': task.difficulty,
                    'is_completed': task.is_completed,
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
            ['id', 'subject_id', 'title', 'description', 'deadline', 'priority', 'difficulty', 'is_completed', 'created_at'],
            payload['data']['tasks'],
        ),
        'schedule_items.csv': (
            ['id', 'subject_id', 'weekday', 'start_time', 'end_time', 'lesson_type', 'room'],
            payload['data']['schedule_items'],
        ),
        'notes.csv': (
            ['id', 'subject_id', 'title', 'content', 'link', 'created_at'],
            payload['data']['notes'],
        ),
    }

    with zipfile.ZipFile(archive_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('export_meta.json', json.dumps({
            'version': payload['version'],
            'exported_at': payload['exported_at'],
            'user': payload['user'],
        }, ensure_ascii=False, indent=2))

        for filename, (fieldnames, rows) in csv_specs.items():
            text_buffer = io.StringIO()
            writer = csv.DictWriter(text_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field) for field in fieldnames})
            archive.writestr(filename, text_buffer.getvalue().encode('utf-8-sig'))

    archive_buffer.seek(0)
    return archive_buffer


def build_download_headers(filename: str):
    return {
        'Content-Disposition': f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote_plus(filename)}',
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    }


def import_user_export_payload(user: User, payload, import_mode: str, db: Session):
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ValueError('В файле нет блока data с данными для импорта.')

    user_payload = payload.get('user', {})
    if isinstance(user_payload, dict):
        imported_schedule_unit = user_payload.get('schedule_unit')
        if imported_schedule_unit in SCHEDULE_UNIT_OPTIONS:
            user.schedule_unit = imported_schedule_unit

    subjects_payload = data.get('subjects', [])
    tasks_payload = data.get('tasks', [])
    schedule_payload = data.get('schedule_items', [])
    notes_payload = data.get('notes', [])

    for collection, label in [
        (subjects_payload, 'subjects'),
        (tasks_payload, 'tasks'),
        (schedule_payload, 'schedule_items'),
        (notes_payload, 'notes'),
    ]:
        if not isinstance(collection, list):
            raise ValueError(f'Поле {label} должно быть списком.')

    subject_id_map = {}

    if import_mode == 'replace':
        db.query(Note).filter(Note.user_id == user.id).delete(synchronize_session=False)
        db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).delete(synchronize_session=False)
        db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
        db.query(Subject).filter(Subject.user_id == user.id).delete(synchronize_session=False)
        db.flush()

    for subject_payload in subjects_payload:
        subject = Subject(
            user_id=user.id,
            name=(subject_payload.get('name') or '').strip() or 'Без названия',
            teacher=subject_payload.get('teacher') or None,
            room=subject_payload.get('room') or None,
            color=subject_payload.get('color') or '#0d6efd',
            notes=subject_payload.get('notes') or None,
        )
        db.add(subject)
        db.flush()
        original_subject_id = subject_payload.get('id')
        if original_subject_id is not None:
            subject_id_map[original_subject_id] = subject.id

    for task_payload in tasks_payload:
        task = Task(
            user_id=user.id,
            subject_id=subject_id_map.get(task_payload.get('subject_id')),
            title=(task_payload.get('title') or '').strip() or 'Без названия',
            description=task_payload.get('description') or None,
            deadline=parse_datetime_value(task_payload.get('deadline')),
            priority=task_payload.get('priority') or 'medium',
            difficulty=task_payload.get('difficulty') or 'medium',
            is_completed=bool(task_payload.get('is_completed', False)),
            created_at=parse_datetime_value(task_payload.get('created_at')) or datetime.utcnow(),
        )
        db.add(task)

    for schedule_payload_item in schedule_payload:
        mapped_subject_id = subject_id_map.get(schedule_payload_item.get('subject_id'))
        if not mapped_subject_id:
            continue

        schedule_item = ScheduleItem(
            user_id=user.id,
            subject_id=mapped_subject_id,
            weekday=int(schedule_payload_item.get('weekday', 0)),
            start_time=parse_time_value(schedule_payload_item.get('start_time')) or datetime.strptime('09:00:00', '%H:%M:%S').time(),
            end_time=parse_time_value(schedule_payload_item.get('end_time')) or datetime.strptime('10:00:00', '%H:%M:%S').time(),
            lesson_type=schedule_payload_item.get('lesson_type') or None,
            room=schedule_payload_item.get('room') or None,
        )
        db.add(schedule_item)

    for note_payload in notes_payload:
        note = Note(
            user_id=user.id,
            subject_id=subject_id_map.get(note_payload.get('subject_id')),
            title=(note_payload.get('title') or '').strip() or 'Без названия',
            content=note_payload.get('content') or None,
            link=note_payload.get('link') or None,
            created_at=parse_datetime_value(note_payload.get('created_at')) or datetime.utcnow(),
        )
        db.add(note)
