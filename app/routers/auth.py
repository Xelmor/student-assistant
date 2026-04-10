from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password, verify_password
from ..database import get_db
from ..models import User
from .common import templates

router = APIRouter()


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
        schedule_unit='class',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session['user_id'] = user.id
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()
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
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()
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
