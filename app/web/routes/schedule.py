from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS
from ...models import ScheduleItem, Subject
from ..dependencies import SCHEDULE_TIME_PRESETS, is_valid_schedule_time_range, parse_schedule_time, require_user, templates, validate_csrf

router = APIRouter()


@router.get('/schedule', response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(
        ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()
    ).all()

    grouped = {i: [] for i in range(7)}
    for item in items:
        grouped[item.weekday].append(item)

    return templates.TemplateResponse(
        request,
        'schedule/schedule.html',
        {
            'user': user,
            'subjects': subjects,
            'grouped': grouped,
            'weekdays': WEEKDAYS,
            'schedule_time_presets': SCHEDULE_TIME_PRESETS,
        }
    )


@router.post('/schedule/add')
async def add_schedule_items(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    form = await request.form()
    subject_id_values = form.getlist('subject_id')
    weekday_values = form.getlist('weekday')
    start_time_values = form.getlist('start_time')
    end_time_values = form.getlist('end_time')
    lesson_type_values = form.getlist('lesson_type')
    room_values = form.getlist('room')

    total_rows = len(subject_id_values)

    for i in range(total_rows):
        current_subject_id = subject_id_values[i] if i < len(subject_id_values) else ''
        current_weekday = weekday_values[i] if i < len(weekday_values) else ''
        current_start_time = start_time_values[i].strip() if i < len(start_time_values) else ''
        current_end_time = end_time_values[i].strip() if i < len(end_time_values) else ''
        current_lesson_type = lesson_type_values[i].strip() if i < len(lesson_type_values) else ''
        current_room = room_values[i].strip() if i < len(room_values) else ''

        selected_weekdays = [
            int(value) for value in current_weekday.split(',')
            if value.strip().isdigit() and 0 <= int(value.strip()) <= 6
        ]

        if not current_subject_id or not selected_weekdays or not current_start_time or not current_end_time:
            continue

        subject = db.query(Subject).filter(
            Subject.id == int(current_subject_id),
            Subject.user_id == user.id
        ).first()

        if not subject:
            continue

        parsed_start_time = parse_schedule_time(current_start_time)
        parsed_end_time = parse_schedule_time(current_end_time)
        if not is_valid_schedule_time_range(parsed_start_time, parsed_end_time):
            continue

        for weekday in selected_weekdays:
            item = ScheduleItem(
                user_id=user.id,
                subject_id=int(current_subject_id),
                weekday=weekday,
                start_time=parsed_start_time,
                end_time=parsed_end_time,
                lesson_type=current_lesson_type or None,
                room=current_room or None,
            )
            db.add(item)

    db.commit()
    return RedirectResponse('/schedule', status_code=302)


@router.post('/schedule/edit/{item_id}')
def edit_schedule_item(
    item_id: int,
    request: Request,
    subject_id: int = Form(...),
    weekday: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    lesson_type: str = Form(''),
    room: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    item = db.query(ScheduleItem).filter(
        ScheduleItem.id == item_id,
        ScheduleItem.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse('/schedule', status_code=302)

    subject = db.query(Subject).filter(
        Subject.id == subject_id,
        Subject.user_id == user.id
    ).first()
    if not subject:
        return RedirectResponse('/schedule', status_code=302)

    item.subject_id = subject_id
    item.weekday = weekday
    parsed_start_time = parse_schedule_time(start_time)
    parsed_end_time = parse_schedule_time(end_time)
    if not is_valid_schedule_time_range(parsed_start_time, parsed_end_time):
        return RedirectResponse('/schedule', status_code=302)

    item.start_time = parsed_start_time
    item.end_time = parsed_end_time
    item.lesson_type = lesson_type.strip() or None
    item.room = room.strip() or None
    db.commit()

    return RedirectResponse('/schedule', status_code=302)


@router.post('/schedule/delete/{item_id}')
def delete_schedule_item(item_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    item = db.query(ScheduleItem).filter(ScheduleItem.id == item_id, ScheduleItem.user_id == user.id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse('/schedule', status_code=302)
