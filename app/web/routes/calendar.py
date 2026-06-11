import io
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS
from ...core.validation import normalize_bounded_text, normalize_choice
from ...models import AcademicEvent, Subject
from ...services.calendar_service import (
    ACADEMIC_EVENT_TYPE_LABELS,
    CALENDAR_EVENT_TYPE_OPTIONS,
    DAY_OVERRIDE_EVENT_TYPE,
    build_calendar_page_context,
    build_ics_calendar,
    normalize_calendar_period,
)
from ...services.data_service import build_download_headers
from ..dependencies import parse_schedule_time, require_user, templates, validate_csrf

router = APIRouter()

FORM_EVENT_TYPES = {option['value'] for option in CALENDAR_EVENT_TYPE_OPTIONS}
MAX_OVERRIDE_DAYS = 62


def calendar_redirect(
    year: int | None = None,
    month: int | None = None,
    selected: str | None = None,
    view: str = 'week',
    error: str | None = None,
):
    params = []
    if year:
        params.append(('year', year))
    if month:
        params.append(('month', month))
    if selected:
        params.append(('selected', selected))
    if view:
        params.append(('view', view if view in {'month', 'week'} else 'week'))
    if error:
        params.append(('calendar_error', error))
    return f"/calendar?{urlencode(params)}" if params else '/calendar'


def parse_date_or_none(raw_value: str | None):
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def parse_time_or_none(raw_value: str | None):
    if not raw_value:
        return None
    try:
        return parse_schedule_time(raw_value)
    except ValueError:
        return None


def get_owned_subject(db: Session, user_id: int, raw_subject_id: str | int | None):
    if raw_subject_id is None or not str(raw_subject_id).strip().isdigit():
        return None
    return db.query(Subject).filter(Subject.id == int(raw_subject_id), Subject.user_id == user_id).first()


def normalize_calendar_event_payload(
    *,
    db: Session,
    user_id: int,
    event_type: str,
    title: str,
    event_date: str,
    start_time: str,
    end_time: str,
    subject_id: str,
    room: str,
    description: str,
):
    normalized_event_type = normalize_choice(
        event_type,
        label='Тип события',
        allowed=FORM_EVENT_TYPES,
    )
    parsed_date = parse_date_or_none(event_date)
    if not parsed_date:
        raise ValueError('Дата события указана неверно.')

    subject = get_owned_subject(db, user_id, subject_id)
    if subject_id.strip() and subject is None:
        raise ValueError('Выбранный предмет для события не найден.')
    normalized_title = normalize_bounded_text(
        title,
        label='Название события',
        max_length=150,
    )
    if not normalized_title and subject:
        if normalized_event_type == 'changed_class':
            normalized_title = subject.name
        else:
            normalized_title = f'{ACADEMIC_EVENT_TYPE_LABELS[normalized_event_type]}: {subject.name}'
    if not normalized_title:
        raise ValueError('Добавь название события или выбери предмет.')

    parsed_start_time = parse_time_or_none(start_time)
    parsed_end_time = parse_time_or_none(end_time)
    if start_time.strip() and not parsed_start_time:
        raise ValueError('Время начала указано в неверном формате.')
    if end_time.strip() and not parsed_end_time:
        raise ValueError('Время окончания указано в неверном формате.')
    if parsed_start_time and parsed_end_time and parsed_start_time >= parsed_end_time:
        raise ValueError('Время окончания должно быть позже времени начала.')

    return {
        'subject_id': subject.id if subject else None,
        'title': normalized_title,
        'event_type': normalized_event_type,
        'event_date': parsed_date,
        'start_time': parsed_start_time,
        'end_time': parsed_end_time,
        'room': (
            normalize_bounded_text(room, label='Аудитория', max_length=50)
            or (subject.room if subject and subject.room else None)
        ),
        'description': normalize_bounded_text(
            description,
            label='Описание события',
            max_length=5000,
        ),
    }


@router.get('/calendar', response_class=HTMLResponse)
def calendar_page(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    selected: str | None = Query(None),
    view: str = Query('week'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    context = build_calendar_page_context(user, db, year, month, selected, view)
    context.update({
        'user': user,
        'weekdays': WEEKDAYS,
        'calendar_error': request.query_params.get('calendar_error'),
    })
    return templates.TemplateResponse(request, 'calendar/calendar.html', context)


@router.get('/calendar/settings')
@router.get('/calendar/settings/')
def calendar_settings_fallback():
    return RedirectResponse('/calendar', status_code=302)


@router.post('/calendar/settings')
@router.post('/calendar/settings/')
def update_calendar_settings(
    request: Request,
    last_study_day: str = Form(''),
    year: int | None = Form(None),
    month: int | None = Form(None),
    selected: str | None = Form(None),
    view: str = Form('week'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    parsed_last_study_day = parse_date_or_none(last_study_day)
    if last_study_day and not parsed_last_study_day:
        return RedirectResponse(
            calendar_redirect(year, month, selected, view, 'Дата указана в неверном формате.'),
            status_code=302,
        )

    try:
        user.last_study_day = parsed_last_study_day
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            calendar_redirect(year, month, selected, view, 'Не удалось сохранить настройки календаря.'),
            status_code=302,
        )

    return RedirectResponse(calendar_redirect(year, month, selected, view), status_code=302)


@router.post('/calendar/session/add')
def add_session_event(
    request: Request,
    event_type: str = Form('exam'),
    title: str = Form(''),
    event_date: str = Form(''),
    start_time: str = Form(''),
    end_time: str = Form(''),
    subject_id: str = Form(''),
    room: str = Form(''),
    description: str = Form(''),
    year: int | None = Form(None),
    month: int | None = Form(None),
    selected: str | None = Form(None),
    view: str = Form('week'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    try:
        payload = normalize_calendar_event_payload(
            db=db,
            user_id=user.id,
            event_type=event_type,
            title=title,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            subject_id=subject_id,
            room=room,
            description=description,
        )
    except ValueError as error:
        return RedirectResponse(calendar_redirect(year, month, selected, view, str(error)), status_code=302)

    db.add(AcademicEvent(user_id=user.id, **payload))
    db.commit()
    parsed_date = payload['event_date']
    return RedirectResponse(calendar_redirect(parsed_date.year, parsed_date.month, parsed_date.isoformat(), view), status_code=302)


@router.post('/calendar/session/edit/{event_id}')
def edit_session_event(
    event_id: int,
    request: Request,
    event_type: str = Form('exam'),
    title: str = Form(''),
    event_date: str = Form(''),
    start_time: str = Form(''),
    end_time: str = Form(''),
    subject_id: str = Form(''),
    room: str = Form(''),
    description: str = Form(''),
    year: int | None = Form(None),
    month: int | None = Form(None),
    selected: str | None = Form(None),
    view: str = Form('week'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    event = db.query(AcademicEvent).filter(AcademicEvent.id == event_id, AcademicEvent.user_id == user.id).first()
    if not event:
        return RedirectResponse(calendar_redirect(year, month, selected, view), status_code=302)

    try:
        payload = normalize_calendar_event_payload(
            db=db,
            user_id=user.id,
            event_type=event_type,
            title=title,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            subject_id=subject_id,
            room=room,
            description=description,
        )
    except ValueError as error:
        return RedirectResponse(calendar_redirect(year, month, selected, view, str(error)), status_code=302)

    for field, value in payload.items():
        setattr(event, field, value)
    db.commit()
    parsed_date = payload['event_date']
    return RedirectResponse(calendar_redirect(parsed_date.year, parsed_date.month, parsed_date.isoformat(), view), status_code=302)


@router.post('/calendar/override/add')
def add_schedule_override(
    request: Request,
    start_date: str = Form(''),
    end_date: str = Form(''),
    title: str = Form(''),
    description: str = Form(''),
    year: int | None = Form(None),
    month: int | None = Form(None),
    selected: str | None = Form(None),
    view: str = Form('week'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    parsed_start = parse_date_or_none(start_date)
    parsed_end = parse_date_or_none(end_date) or parsed_start
    if not parsed_start or not parsed_end:
        return RedirectResponse(calendar_redirect(year, month, selected, view, 'Диапазон дат указан неверно.'), status_code=302)
    if parsed_end < parsed_start:
        parsed_end = parsed_start
    if (parsed_end - parsed_start).days + 1 > MAX_OVERRIDE_DAYS:
        return RedirectResponse(
            calendar_redirect(year, month, selected, view, f'Можно отметить не больше {MAX_OVERRIDE_DAYS} дней за раз.'),
            status_code=302,
        )

    existing_dates = {
        event.event_date
        for event in db.query(AcademicEvent).filter(
            AcademicEvent.user_id == user.id,
            AcademicEvent.event_type == DAY_OVERRIDE_EVENT_TYPE,
            AcademicEvent.event_date >= parsed_start,
            AcademicEvent.event_date <= parsed_end,
        )
    }
    try:
        normalized_title = (
            normalize_bounded_text(title, label='Название особого дня', max_length=150)
            or 'День не по расписанию'
        )
        normalized_description = normalize_bounded_text(
            description,
            label='Описание особого дня',
            max_length=5000,
        )
    except ValueError as error:
        return RedirectResponse(calendar_redirect(year, month, selected, view, str(error)), status_code=302)
    current_day = parsed_start
    while current_day <= parsed_end:
        if current_day not in existing_dates:
            db.add(
                AcademicEvent(
                    user_id=user.id,
                    title=normalized_title,
                    event_type=DAY_OVERRIDE_EVENT_TYPE,
                    event_date=current_day,
                    description=normalized_description,
                )
            )
        current_day += timedelta(days=1)

    db.commit()
    return RedirectResponse(calendar_redirect(parsed_start.year, parsed_start.month, parsed_start.isoformat(), view), status_code=302)


@router.post('/calendar/session/delete/{event_id}')
def delete_session_event(
    event_id: int,
    request: Request,
    year: int | None = Form(None),
    month: int | None = Form(None),
    selected: str | None = Form(None),
    view: str = Form('week'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    event = db.query(AcademicEvent).filter(AcademicEvent.id == event_id, AcademicEvent.user_id == user.id).first()
    if event:
        db.delete(event)
        db.commit()
    return RedirectResponse(calendar_redirect(year, month, selected, view), status_code=302)


@router.get('/calendar/export/ics')
def export_calendar_ics(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    safe_year, safe_month = normalize_calendar_period(year, month)
    calendar_bytes = build_ics_calendar(user, db, safe_year, safe_month)
    filename = f'{user.username}_calendar_{safe_year}-{safe_month:02d}.ics'
    return StreamingResponse(
        io.BytesIO(calendar_bytes),
        media_type='text/calendar; charset=utf-8',
        headers=build_download_headers(filename),
    )
