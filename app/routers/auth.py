from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password, verify_password
from ..database import get_db
from ..models import User
from ..password_reset import (
    generate_password_reset_token,
    load_password_reset_payload,
    password_reset_enabled,
    send_password_reset_email,
    validate_password_reset_token,
)
from .common import templates, validate_csrf

router = APIRouter()


def normalize_username(value: str) -> str:
    return value.strip()


def normalize_email(value: str) -> str:
    return value.strip().lower()


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
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    username = normalize_username(username)
    email = normalize_email(email)

    existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'register.html',
            {'error': 'Пользователь с таким логином или email уже существует.'},
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
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    username = normalize_username(username)
    normalized_email = normalize_email(username)

    user = db.query(User).filter((User.username == username) | (User.email == normalized_email)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            'login.html',
            {'error': 'Неверный логин или пароль.'},
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
        {'error': None, 'success': None, 'email': ''},
    )


@router.post('/forgot-password', response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    email = normalize_email(email)

    if not password_reset_enabled():
        return templates.TemplateResponse(
            request,
            'forgot_password.html',
            {
                'error': 'Восстановление пароля по email пока не настроено. Заполните SMTP-параметры в окружении приложения.',
                'success': None,
                'email': email,
            },
        )

    user = db.query(User).filter(User.email == email).first()
    if user:
        reset_token = generate_password_reset_token(user)
        reset_url = str(request.url_for('reset_password_page').include_query_params(token=reset_token))
        try:
            send_password_reset_email(user.email, reset_url)
        except Exception:
            return templates.TemplateResponse(
                request,
                'forgot_password.html',
                {
                    'error': 'Не удалось отправить письмо для восстановления пароля. Проверьте SMTP-настройки и попробуйте снова.',
                    'success': None,
                    'email': email,
                },
            )

    return templates.TemplateResponse(
        request,
        'forgot_password.html',
        {
            'error': None,
            'success': 'Если аккаунт с таким email существует, мы отправили письмо со ссылкой для сброса пароля.',
            'email': email,
        },
    )


@router.get('/reset-password', response_class=HTMLResponse, name='reset_password_page')
def reset_password_page(request: Request, token: str = '', db: Session = Depends(get_db)):
    payload = load_password_reset_payload(token)
    user = db.query(User).filter(User.id == payload.get('user_id')).first() if payload else None
    token_valid = validate_password_reset_token(token, user)

    return templates.TemplateResponse(
        request,
        'reset_password.html',
        {
            'error': None if token_valid else 'Ссылка для сброса пароля недействительна или устарела.',
            'success': None,
            'token': token,
            'token_valid': token_valid,
        },
    )


@router.post('/reset-password', response_class=HTMLResponse)
def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    payload = load_password_reset_payload(token)
    user = db.query(User).filter(User.id == payload.get('user_id')).first() if payload else None
    token_valid = validate_password_reset_token(token, user)

    if not token_valid:
        return templates.TemplateResponse(
            request,
            'reset_password.html',
            {
                'error': 'Ссылка для сброса пароля недействительна или устарела.',
                'success': None,
                'token': token,
                'token_valid': False,
            },
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            'reset_password.html',
            {
                'error': 'Пароли не совпадают.',
                'success': None,
                'token': token,
                'token_valid': True,
            },
        )

    if len(new_password) < 6:
        return templates.TemplateResponse(
            request,
            'reset_password.html',
            {
                'error': 'Пароль должен быть не короче 6 символов.',
                'success': None,
                'token': token,
                'token_valid': True,
            },
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        request,
        'reset_password.html',
        {
            'error': None,
            'success': 'Пароль обновлен. Теперь можно войти с новым паролем.',
            'token': '',
            'token_valid': False,
        },
    )


@router.post('/logout')
def logout(request: Request, _: None = Depends(validate_csrf)):
    request.session.clear()
    return RedirectResponse('/', status_code=302)
