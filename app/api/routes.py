from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.time import WEEKDAYS, current_time
from ..models import Note, ScheduleItem, Subject, Task, User
from ..services.telegram_link_service import assign_telegram_link_code, telegram_link_code_is_active
from ..web.dependencies import require_user
from .dependencies import get_user_by_chat_id, require_bot_token
from .schemas import (
    CreateTaskRequest,
    NoteResponse,
    ReminderSettingsResponse,
    ReminderSettingsUpdate,
    ScheduleItemResponse,
    SubjectResponse,
    TaskResponse,
    TelegramLinkCodeResponse,
    TelegramLinkConfirmRequest,
    TelegramLinkConfirmResponse,
)

router = APIRouter(prefix='/api/v1', tags=['telegram-bot'])


def serialize_task(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        deadline=task.deadline,
        priority=task.priority,
        difficulty=task.difficulty,
        is_completed=task.is_completed,
        subject_id=task.subject_id,
        subject_name=task.subject.name if task.subject else None,
        created_at=task.created_at,
    )


def serialize_note(note: Note) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        link=note.link,
        subject_name=note.subject.name if note.subject else None,
        created_at=note.created_at,
    )


def serialize_schedule_item(item: ScheduleItem) -> ScheduleItemResponse:
    return ScheduleItemResponse(
        id=item.id,
        weekday=item.weekday,
        weekday_name=WEEKDAYS.get(item.weekday, str(item.weekday)),
        start_time=item.start_time.strftime('%H:%M'),
        end_time=item.end_time.strftime('%H:%M'),
        lesson_type=item.lesson_type,
        room=item.room,
        subject_id=item.subject_id,
        subject_name=item.subject.name,
    )


def build_schedule_payload(items: list[ScheduleItem]):
    grouped: dict[str, list[ScheduleItemResponse]] = defaultdict(list)
    for item in items:
        weekday_name = WEEKDAYS.get(item.weekday, str(item.weekday))
        grouped[weekday_name].append(serialize_schedule_item(item))
    return grouped


def get_link_code_for_user(user: User, db: Session) -> TelegramLinkCodeResponse:
    if not telegram_link_code_is_active(user):
        assign_telegram_link_code(user, ttl_minutes=settings.telegram_link_code_ttl_minutes)
        db.commit()
        db.refresh(user)

    return TelegramLinkCodeResponse(
        code=user.telegram_link_code or '',
        expires_at=user.telegram_link_code_expires_at,
        linked_chat_id=user.telegram_chat_id,
        linked_username=user.telegram_username,
    )


@router.post('/telegram/link/code', response_model=TelegramLinkCodeResponse)
def create_telegram_link_code(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail='Authentication required.')

    assign_telegram_link_code(user, ttl_minutes=settings.telegram_link_code_ttl_minutes)
    db.commit()
    db.refresh(user)
    return TelegramLinkCodeResponse(
        code=user.telegram_link_code or '',
        expires_at=user.telegram_link_code_expires_at,
        linked_chat_id=user.telegram_chat_id,
        linked_username=user.telegram_username,
    )


@router.get('/telegram/link/code', response_model=TelegramLinkCodeResponse)
def get_telegram_link_code(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail='Authentication required.')
    return get_link_code_for_user(user, db)


@router.post('/telegram/link/confirm', response_model=TelegramLinkConfirmResponse)
def confirm_telegram_link(
    payload: TelegramLinkConfirmRequest,
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.telegram_link_code == payload.code).first()
    if not user or not telegram_link_code_is_active(user):
        raise HTTPException(status_code=400, detail='Invalid or expired link code.')

    existing_user = db.query(User).filter(User.telegram_chat_id == payload.chat_id, User.id != user.id).first()
    if existing_user:
        raise HTTPException(status_code=409, detail='This Telegram account is already linked to another user.')

    user.telegram_chat_id = payload.chat_id
    user.telegram_username = payload.telegram_username
    user.telegram_linked_at = current_time().replace(tzinfo=None)
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    user.telegram_notifications_enabled = True
    user.telegram_deadline_reminders_enabled = True
    user.telegram_schedule_reminders_enabled = True
    db.commit()
    return TelegramLinkConfirmResponse(success=True, username=user.username)


def resolve_bot_user(chat_id: int, db: Session) -> User:
    return get_user_by_chat_id(db, chat_id)


@router.get('/telegram/me')
def get_me(
    chat_id: int = Query(...),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'group_name': user.group_name,
        'course': user.course,
        'telegram_username': user.telegram_username,
        'linked_at': user.telegram_linked_at,
    }


@router.get('/telegram/subjects', response_model=list[SubjectResponse])
def get_subjects(
    chat_id: int = Query(...),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return [SubjectResponse.model_validate(subject) for subject in subjects]


@router.get('/telegram/tasks', response_model=list[TaskResponse])
def get_tasks(
    chat_id: int = Query(...),
    status: str = Query(default='active'),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    query = db.query(Task).filter(Task.user_id == user.id)
    if status == 'active':
        query = query.filter(Task.is_completed.is_(False))
    elif status == 'completed':
        query = query.filter(Task.is_completed.is_(True))
    tasks = query.order_by(Task.is_completed.asc(), Task.deadline.asc(), Task.created_at.desc()).limit(limit).all()
    return [serialize_task(task) for task in tasks]


@router.get('/telegram/deadlines', response_model=list[TaskResponse])
def get_deadlines(
    chat_id: int = Query(...),
    limit: int = Query(default=10, ge=1, le=100),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.is_completed.is_(False), Task.deadline.is_not(None))
        .order_by(Task.deadline.asc())
        .limit(limit)
        .all()
    )
    return [serialize_task(task) for task in tasks]


@router.get('/telegram/notes', response_model=list[NoteResponse])
def get_notes(
    chat_id: int = Query(...),
    limit: int = Query(default=10, ge=1, le=100),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).limit(limit).all()
    return [serialize_note(note) for note in notes]


@router.get('/telegram/schedule')
def get_schedule(
    chat_id: int = Query(...),
    scope: str = Query(default='week'),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    query = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id)
    if scope == 'today':
        query = query.filter(ScheduleItem.weekday == current_time().weekday())
    items = query.order_by(ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()).all()
    return {
        'scope': scope,
        'schedule': build_schedule_payload(items),
    }


@router.post('/telegram/tasks', response_model=TaskResponse, status_code=201)
def create_task(
    payload: CreateTaskRequest,
    chat_id: int = Query(...),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    normalized_title = payload.title.strip()
    if not normalized_title:
        raise HTTPException(status_code=422, detail='Task title is required.')

    if payload.subject_id is not None:
        subject = db.query(Subject).filter(Subject.id == payload.subject_id, Subject.user_id == user.id).first()
        if not subject:
            raise HTTPException(status_code=404, detail='Subject not found.')

    task = Task(
        user_id=user.id,
        title=normalized_title,
        description=(payload.description or '').strip() or None,
        subject_id=payload.subject_id,
        deadline=payload.deadline,
        priority=payload.priority,
        difficulty=payload.difficulty,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return serialize_task(task)


@router.get('/telegram/reminders', response_model=ReminderSettingsResponse)
def get_reminders(
    chat_id: int = Query(...),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)
    return ReminderSettingsResponse(
        notifications_enabled=user.telegram_notifications_enabled,
        deadline_reminders_enabled=user.telegram_deadline_reminders_enabled,
        schedule_reminders_enabled=user.telegram_schedule_reminders_enabled,
    )


@router.put('/telegram/reminders', response_model=ReminderSettingsResponse)
def update_reminders(
    payload: ReminderSettingsUpdate,
    chat_id: int = Query(...),
    _: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    user = resolve_bot_user(chat_id, db)

    if payload.notifications_enabled is not None:
        user.telegram_notifications_enabled = payload.notifications_enabled
        if not payload.notifications_enabled:
            user.telegram_deadline_reminders_enabled = False
            user.telegram_schedule_reminders_enabled = False
    if payload.deadline_reminders_enabled is not None:
        user.telegram_deadline_reminders_enabled = payload.deadline_reminders_enabled
    if payload.schedule_reminders_enabled is not None:
        user.telegram_schedule_reminders_enabled = payload.schedule_reminders_enabled
    if user.telegram_deadline_reminders_enabled or user.telegram_schedule_reminders_enabled:
        user.telegram_notifications_enabled = True

    db.commit()
    return ReminderSettingsResponse(
        notifications_enabled=user.telegram_notifications_enabled,
        deadline_reminders_enabled=user.telegram_deadline_reminders_enabled,
        schedule_reminders_enabled=user.telegram_schedule_reminders_enabled,
    )
