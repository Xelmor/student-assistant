from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS
from ...core.validation import normalize_bounded_text, safe_hex_color
from ...models import ScheduleItem, Subject, Task
from ..dependencies import (
    SCHEDULE_TIME_PRESETS,
    is_valid_schedule_time_range,
    parse_schedule_time,
    require_user,
    templates,
    validate_csrf,
)

router = APIRouter()


def build_schedule_redirect(*, form_error: str | None = None, selected_item_id: int | None = None) -> str:
    params = {}
    if form_error:
        params['form_error'] = form_error
    if selected_item_id is not None:
        params['item'] = str(selected_item_id)
    query = urlencode(params)
    return f'/schedule?{query}' if query else '/schedule'


def is_schedule_row_blank(subject_id: str, weekday: str, start_time: str, end_time: str, lesson_type: str, room: str) -> bool:
    return not any(
        [
            str(subject_id).strip(),
            str(weekday).strip(),
            str(start_time).strip(),
            str(end_time).strip(),
            str(lesson_type).strip(),
            str(room).strip(),
        ]
    )


def row_error(row_number: int, message: str) -> ValueError:
    return ValueError(f'Строка {row_number}: {message}')


def parse_schedule_weekday(value: str | int) -> int:
    normalized_value = str(value).strip()
    if not normalized_value.isdigit():
        raise ValueError('Не удалось определить день недели для занятия.')

    weekday = int(normalized_value)
    if weekday < 0 or weekday > 6:
        raise ValueError('День недели для занятия указан некорректно.')
    return weekday


def parse_schedule_subject_id(value: str | int) -> int:
    normalized_value = str(value).strip()
    if not normalized_value.isdigit():
        raise ValueError('Не удалось определить выбранный предмет для занятия.')
    return int(normalized_value)


def parse_schedule_time_range(start_time: str, end_time: str):
    try:
        parsed_start_time = parse_schedule_time(start_time)
        parsed_end_time = parse_schedule_time(end_time)
    except ValueError as error:
        raise ValueError('Время занятия указано в неверном формате.') from error

    if not is_valid_schedule_time_range(parsed_start_time, parsed_end_time):
        raise ValueError('Время окончания должно быть позже времени начала.')

    return parsed_start_time, parsed_end_time


def validate_schedule_row(
    *,
    row_number: int,
    subject_id_raw: str,
    weekday_raw: str,
    start_time_raw: str,
    end_time_raw: str,
    lesson_type_raw: str,
    room_raw: str,
):
    normalized_subject_id = str(subject_id_raw).strip()
    normalized_weekday = str(weekday_raw).strip()
    normalized_start_time = str(start_time_raw).strip()
    normalized_end_time = str(end_time_raw).strip()
    normalized_lesson_type = str(lesson_type_raw).strip()
    normalized_room = str(room_raw).strip()

    if is_schedule_row_blank(
        normalized_subject_id,
        normalized_weekday,
        normalized_start_time,
        normalized_end_time,
        normalized_lesson_type,
        normalized_room,
    ):
        return None

    raw_weekday_values = [value.strip() for value in normalized_weekday.split(',') if value.strip()]
    missing_fields = []
    if not normalized_subject_id:
        missing_fields.append('предмет')
    if not raw_weekday_values:
        missing_fields.append('день недели')
    if not normalized_start_time:
        missing_fields.append('время начала')
    if not normalized_end_time:
        missing_fields.append('время окончания')
    if missing_fields:
        raise row_error(row_number, f"заполнены не все обязательные поля: {', '.join(missing_fields)}.")

    try:
        parsed_subject_id = parse_schedule_subject_id(normalized_subject_id)
        selected_weekdays = [parse_schedule_weekday(value) for value in raw_weekday_values]
        parsed_start_time, parsed_end_time = parse_schedule_time_range(
            normalized_start_time,
            normalized_end_time,
        )
        normalized_lesson_type = normalize_bounded_text(
            normalized_lesson_type,
            label='Тип занятия',
            max_length=50,
        )
        normalized_room = normalize_bounded_text(
            normalized_room,
            label='Аудитория',
            max_length=50,
        )
    except ValueError as error:
        raise row_error(row_number, str(error)) from error

    return {
        'row_number': row_number,
        'subject_id': parsed_subject_id,
        'weekdays': selected_weekdays,
        'start_time': parsed_start_time,
        'end_time': parsed_end_time,
        'lesson_type': normalized_lesson_type,
        'room': normalized_room,
    }


def get_schedule_conflict(
    db: Session,
    *,
    user_id: int,
    weekday: int,
    start_time,
    end_time,
    exclude_item_id: int | None = None,
) -> ScheduleItem | None:
    query = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user_id,
        ScheduleItem.weekday == weekday,
        and_(ScheduleItem.start_time < end_time, ScheduleItem.end_time > start_time),
    )
    if exclude_item_id is not None:
        query = query.filter(ScheduleItem.id != exclude_item_id)
    return query.order_by(ScheduleItem.start_time.asc()).first()


def check_schedule_conflict(
    db: Session,
    *,
    user_id: int,
    weekday: int,
    start_time,
    end_time,
    row_number: int,
    exclude_item_id: int | None = None,
):
    conflict = get_schedule_conflict(
        db,
        user_id=user_id,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        exclude_item_id=exclude_item_id,
    )
    if conflict is None:
        return

    raise row_error(
        row_number,
        (
            f'занятие пересекается с уже существующей парой '
            f'{WEEKDAYS[weekday]} {conflict.start_time.strftime("%H:%M")} - {conflict.end_time.strftime("%H:%M")}.'
        ),
    )


def check_pending_schedule_conflict(
    pending_items: list[dict],
    *,
    weekday: int,
    start_time,
    end_time,
    row_number: int,
):
    for pending_item in pending_items:
        if pending_item['weekday'] != weekday:
            continue
        if pending_item['start_time'] < end_time and pending_item['end_time'] > start_time:
            raise row_error(
                row_number,
                (
                    f'занятие пересекается с другой строкой формы: '
                    f'{WEEKDAYS[weekday]} {pending_item["start_time"].strftime("%H:%M")} - '
                    f'{pending_item["end_time"].strftime("%H:%M")}.'
                ),
            )


@router.get('/schedule', response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    form_error = request.query_params.get('form_error')
    selected_item_id = request.query_params.get('item')

    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    items = db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).order_by(
        ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc()
    ).all()
    for item in items:
        item.safe_subject_color = safe_hex_color(item.subject.color, default='#8b5cf6')

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
            'form_error': form_error,
            'selected_item_id': int(selected_item_id) if selected_item_id and selected_item_id.isdigit() else None,
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
    pending_items: list[dict] = []

    for i in range(total_rows):
        current_subject_id = subject_id_values[i] if i < len(subject_id_values) else ''
        current_weekday = weekday_values[i] if i < len(weekday_values) else ''
        current_start_time = start_time_values[i].strip() if i < len(start_time_values) else ''
        current_end_time = end_time_values[i].strip() if i < len(end_time_values) else ''
        current_lesson_type = lesson_type_values[i].strip() if i < len(lesson_type_values) else ''
        current_room = room_values[i].strip() if i < len(room_values) else ''
        row_number = i + 1

        try:
            validated_row = validate_schedule_row(
                row_number=row_number,
                subject_id_raw=current_subject_id,
                weekday_raw=current_weekday,
                start_time_raw=current_start_time,
                end_time_raw=current_end_time,
                lesson_type_raw=current_lesson_type,
                room_raw=current_room,
            )
        except ValueError as error:
            return RedirectResponse(build_schedule_redirect(form_error=str(error)), status_code=302)

        if validated_row is None:
            continue

        subject = db.query(Subject).filter(
            Subject.id == validated_row['subject_id'],
            Subject.user_id == user.id,
        ).first()
        if not subject:
            return RedirectResponse(
                build_schedule_redirect(
                    form_error=f'Строка {row_number}: выбранный предмет для занятия не найден.'
                ),
                status_code=302,
            )

        for weekday in validated_row['weekdays']:
            try:
                check_pending_schedule_conflict(
                    pending_items,
                    weekday=weekday,
                    start_time=validated_row['start_time'],
                    end_time=validated_row['end_time'],
                    row_number=row_number,
                )
                check_schedule_conflict(
                    db,
                    user_id=user.id,
                    weekday=weekday,
                    start_time=validated_row['start_time'],
                    end_time=validated_row['end_time'],
                    row_number=row_number,
                )
            except ValueError as error:
                return RedirectResponse(build_schedule_redirect(form_error=str(error)), status_code=302)

            pending_items.append(
                {
                    'weekday': weekday,
                    'start_time': validated_row['start_time'],
                    'end_time': validated_row['end_time'],
                }
            )

            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=validated_row['subject_id'],
                    weekday=weekday,
                    start_time=validated_row['start_time'],
                    end_time=validated_row['end_time'],
                    lesson_type=validated_row['lesson_type'],
                    room=validated_row['room'],
                )
            )

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

    try:
        parsed_weekday = parse_schedule_weekday(weekday)
        parsed_start_time, parsed_end_time = parse_schedule_time_range(start_time, end_time)
        normalized_lesson_type = normalize_bounded_text(
            lesson_type,
            label='Тип занятия',
            max_length=50,
        )
        normalized_room = normalize_bounded_text(
            room,
            label='Аудитория',
            max_length=50,
        )
    except ValueError as error:
        return RedirectResponse(
            build_schedule_redirect(form_error=str(error), selected_item_id=item_id),
            status_code=302,
        )

    subject = db.query(Subject).filter(
        Subject.id == subject_id,
        Subject.user_id == user.id
    ).first()
    if not subject:
        return RedirectResponse(
            build_schedule_redirect(
                form_error='Выбранный предмет для занятия не найден.',
                selected_item_id=item_id,
            ),
            status_code=302,
        )

    try:
        check_schedule_conflict(
            db,
            user_id=user.id,
            weekday=parsed_weekday,
            start_time=parsed_start_time,
            end_time=parsed_end_time,
            row_number=1,
            exclude_item_id=item_id,
        )
    except ValueError as error:
        return RedirectResponse(
            build_schedule_redirect(form_error=str(error), selected_item_id=item_id),
            status_code=302,
        )

    item.subject_id = subject_id
    item.weekday = parsed_weekday
    item.start_time = parsed_start_time
    item.end_time = parsed_end_time
    item.lesson_type = normalized_lesson_type
    item.room = normalized_room
    db.commit()

    return RedirectResponse('/schedule', status_code=302)


@router.post('/schedule/delete/{item_id}')
def delete_schedule_item(item_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    item = db.query(ScheduleItem).filter(ScheduleItem.id == item_id, ScheduleItem.user_id == user.id).first()
    if item:
        db.query(Task).filter(Task.user_id == user.id, Task.schedule_item_id == item.id).update(
            {Task.schedule_item_id: None},
            synchronize_session=False,
        )
        db.delete(item)
        db.commit()
    return RedirectResponse('/schedule', status_code=302)
