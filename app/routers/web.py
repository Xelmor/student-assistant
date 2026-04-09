from datetime import datetime
import calendar
import os
import random
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Subject, Task, ScheduleItem, Note
from ..auth import hash_password, verify_password, get_current_user
from ..utils import WEEKDAYS, calculate_task_score

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
SCHEDULE_TIME_PRESETS = {
    'free': {
        'label': 'Свободный',
        'slots': [],
    },
    'university': {
        'label': 'ВУЗ',
        'slots': [
            {'key': 'u1', 'label': '1 пара: 09:00 - 10:30', 'start': '09:00', 'end': '10:30'},
            {'key': 'u2', 'label': '2 пара: 10:40 - 12:10', 'start': '10:40', 'end': '12:10'},
            {'key': 'u3', 'label': '3 пара: 12:40 - 14:10', 'start': '12:40', 'end': '14:10'},
            {'key': 'u4', 'label': '4 пара: 14:20 - 15:50', 'start': '14:20', 'end': '15:50'},
            {'key': 'u5', 'label': '5 пара: 16:20 - 17:50', 'start': '16:20', 'end': '17:50'},
            {'key': 'u6', 'label': '6 пара: 18:00 - 19:30', 'start': '18:00', 'end': '19:30'},
        ],
    },
    'school': {
        'label': 'Школа',
        'slots': [
            {'key': 's1', 'label': '1 урок: 08:00 - 08:40', 'start': '08:00', 'end': '08:40'},
            {'key': 's2', 'label': '2 урок: 08:50 - 09:30', 'start': '08:50', 'end': '09:30'},
            {'key': 's3', 'label': '3 урок: 09:45 - 10:25', 'start': '09:45', 'end': '10:25'},
            {'key': 's4', 'label': '4 урок: 10:40 - 11:20', 'start': '10:40', 'end': '11:20'},
            {'key': 's5', 'label': '5 урок: 11:30 - 12:10', 'start': '11:30', 'end': '12:10'},
        ],
    },
}
MOTIVATIONAL_QUOTES = [
    'Маленький шаг сегодня делает большую разницу к концу семестра.',
    'Не нужно делать все идеально, нужно просто двигаться вперед.',
    'Одна закрытая задача сегодня лучше десяти отложенных на потом.',
    'Стабильность в учебе сильнее, чем редкие рывки в последний момент.',
    'Каждая пара и каждая заметка сейчас работают на твой будущий результат.',
    'Даже короткая учебная сессия сегодня приближает тебя к цели.',
    'Спокойный ритм и ясный план всегда выигрывают у хаоса.',
]


def require_user(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        return None
    return user


def parse_schedule_time(value: str):
    normalized_value = value.strip()
    if len(normalized_value) == 4 and normalized_value[1] == ':':
        normalized_value = f'0{normalized_value}'
    return datetime.strptime(normalized_value, '%H:%M').time()


def is_valid_schedule_time_range(start_time, end_time):
    return start_time < end_time


def is_local_private_data_enabled(request: Request) -> bool:
    enabled = os.getenv('ALLOW_LOCAL_PRIVATE_DATA', 'false').lower() == 'true'
    client_host = request.client.host if request.client else ''
    return enabled and client_host in {'127.0.0.1', '::1', 'localhost'}


@router.get('/', response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse('/dashboard', status_code=302)
    return templates.TemplateResponse(request, 'index.html', {})


@router.get('/register', response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, 'register.html', {'error': None})


@router.post('/register', response_class=HTMLResponse)
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    group_name: str = Form(''),
    course: int | None = Form(None),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'register.html',
            {'error': 'Пользователь с таким логином или email уже существует.'}
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        group_name=group_name or None,
        course=course,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session['user_id'] = user.id
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, 'login.html', {'error': None})


@router.post('/login', response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            'login.html',
            {'error': 'Неверный логин или пароль.'}
        )
    request.session['user_id'] = user.id
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/forgot-password', response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        'forgot_password.html',
        {'error': None, 'success': None}
    )


@router.post('/forgot-password', response_class=HTMLResponse)
def forgot_password(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пароли не совпадают.', 'success': None}
        )

    if len(new_password) < 6:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пароль должен быть не короче 6 символов.', 'success': None}
        )

    user = db.query(User).filter(User.username == username, User.email == email).first()
    if not user:
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {'error': 'Пользователь с таким логином и email не найден.', 'success': None}
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        request,
        'forgot_password.html',
        {'error': None, 'success': 'Пароль обновлен. Теперь можно войти с новым паролем.'}
    )


@router.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/', status_code=302)


@router.get('/local-profile', response_class=HTMLResponse)
def local_profile_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if not is_local_private_data_enabled(request):
        return RedirectResponse('/dashboard', status_code=302)

    return templates.TemplateResponse(
        request,
        'local_profile.html',
        {
            'user': user,
        }
    )


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = datetime.now()
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    pending_tasks = [t for t in tasks if not t.is_completed]
    completed_tasks = [t for t in tasks if t.is_completed]
    overdue_tasks = [t for t in pending_tasks if t.deadline and t.deadline < now]
    urgent_tasks = sorted(pending_tasks, key=calculate_task_score, reverse=True)[:5]

    today_weekday = now.weekday()
    today_schedule = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user.id,
        ScheduleItem.weekday == today_weekday,
    ).order_by(ScheduleItem.start_time.asc()).all()
    now_time = now.time()
    active_schedule_item = None
    next_schedule_item = None
    active_schedule_remaining_seconds = 0

    for item in today_schedule:
        if item.start_time <= now_time < item.end_time:
            active_schedule_item = item
            lesson_end = datetime.combine(now.date(), item.end_time)
            active_schedule_remaining_seconds = max(0, int((lesson_end - now).total_seconds()))
            break
        if now_time < item.start_time and next_schedule_item is None:
            next_schedule_item = item

    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(now.year, now.month)
    calendar_days = []
    for week in month_matrix:
        for date_value in week:
            calendar_days.append({
                'day': date_value.day,
                'in_month': date_value.month == now.month,
                'is_today': date_value == now.date(),
            })

    context = {
        'user': user,
        'local_private_data_available': is_local_private_data_enabled(request),
        'subjects_count': db.query(Subject).filter(Subject.user_id == user.id).count(),
        'pending_count': len(pending_tasks),
        'completed_count': len(completed_tasks),
        'overdue_count': len(overdue_tasks),
        'urgent_tasks': urgent_tasks,
        'today_schedule': today_schedule,
        'active_schedule_item': active_schedule_item,
        'next_schedule_item': next_schedule_item,
        'active_schedule_remaining_seconds': active_schedule_remaining_seconds,
        'weekdays': WEEKDAYS,
        'now': now,
        'calendar_days': calendar_days,
        'motivation_quote': random.choice(MOTIVATIONAL_QUOTES),
    }
    return templates.TemplateResponse(request, 'dashboard.html', context)


@router.get('/subjects', response_class=HTMLResponse)
def subjects_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(request, 'subjects.html', {'user': user, 'subjects': subjects})


@router.post('/subjects/add')
def add_subject(
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subject = Subject(
        user_id=user.id,
        name=name,
        teacher=teacher or None,
        room=room or None,
        color=color,
        notes=notes or None,
    )
    db.add(subject)
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.post('/subjects/edit/{subject_id}')
def edit_subject(
    subject_id: int,
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if not subject:
        return RedirectResponse('/subjects', status_code=302)

    subject.name = name
    subject.teacher = teacher or None
    subject.room = room or None
    subject.color = color
    subject.notes = notes or None
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.get('/subjects/delete/{subject_id}')
def delete_subject(subject_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if subject:
        db.delete(subject)
        db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.is_completed.asc(), Task.deadline.asc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'tasks.html',
        {
            'user': user,
            'tasks': tasks,
            'subjects': subjects,
            'now': datetime.now(),
        }
    )


@router.post('/tasks/add')
def add_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    deadline_value = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task = Task(
        user_id=user.id,
        subject_id=subject_id if subject_id else None,
        title=title,
        description=description or None,
        deadline=deadline_value,
        priority=priority,
        difficulty=difficulty,
    )
    db.add(task)
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.post('/tasks/edit/{task_id}')
def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        return RedirectResponse('/tasks', status_code=302)

    if subject_id:
        subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/tasks', status_code=302)

    task.title = title
    task.description = description or None
    task.subject_id = subject_id if subject_id else None
    task.deadline = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task.priority = priority
    task.difficulty = difficulty
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/toggle/{task_id}')
def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        task.is_completed = not task.is_completed
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/delete/{task_id}')
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


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
        'schedule.html',
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

        if not current_subject_id or current_weekday == '' or not current_start_time or not current_end_time:
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

        item = ScheduleItem(
            user_id=user.id,
            subject_id=int(current_subject_id),
            weekday=int(current_weekday),
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


@router.get('/schedule/delete/{item_id}')
def delete_schedule_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    item = db.query(ScheduleItem).filter(ScheduleItem.id == item_id, ScheduleItem.user_id == user.id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse('/schedule', status_code=302)


@router.get('/notes', response_class=HTMLResponse)
def notes_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'notes.html',
        {
            'user': user,
            'notes': notes,
            'subjects': subjects,
        }
    )


@router.post('/notes/add')
def add_note(
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    note = Note(
        user_id=user.id,
        subject_id=subject_id if subject_id else None,
        title=title,
        content=content or None,
        link=link or None,
    )
    db.add(note)
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/delete/{note_id}')
def delete_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if note:
        db.delete(note)
        db.commit()
    return RedirectResponse('/notes', status_code=302)
