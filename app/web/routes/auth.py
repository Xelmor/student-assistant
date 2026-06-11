import logging
import secrets
from urllib.parse import urlencode

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.config import settings
from ...core.rate_limit import auth_rate_limiter, enforce_rate_limit, rate_limit_key
from ...core.security import get_current_user, hash_password, verify_password
from ...core.validation import normalize_bounded_text
from ...models import User
from ...services.password_reset_service import (
    generate_password_reset_token,
    load_password_reset_payload,
    password_reset_enabled,
    send_password_reset_email,
    validate_password_reset_token,
)
from ..dependencies import templates, validate_csrf

router = APIRouter()
logger = logging.getLogger(__name__)

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_LENGTH_ERROR = (
    f'Пароль должен содержать от {PASSWORD_MIN_LENGTH} до {PASSWORD_MAX_LENGTH} символов.'
)
ACCOUNT_IDENTITY_ERROR = 'Логин и email не должны быть пустыми.'
PASSWORD_RESET_GENERIC_SUCCESS = 'Если email найден, инструкция по сбросу уже отправлена.'


def normalize_username(value: str) -> str:
    return value.strip()


def normalize_username_lookup(value: str) -> str:
    return normalize_username(value).lower()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def validate_and_normalize_email(value: str) -> str:
    normalized = normalize_email(value)
    if len(normalized) > 120:
        raise ValueError('Email не должен быть длиннее 120 символов.')
    try:
        result = validate_email(normalized, check_deliverability=False)
    except EmailNotValidError as error:
        raise ValueError('Введите корректный email.') from error
    return result.normalized.lower()


def normalize_account_identity(username: str, email: str) -> tuple[str, str]:
    if not username.strip() or not email.strip():
        raise ValueError(ACCOUNT_IDENTITY_ERROR)

    normalized_username = normalize_bounded_text(
        username,
        label='Логин',
        max_length=50,
        required=True,
    ) or ''
    normalized_email = validate_and_normalize_email(email)
    return normalized_username, normalized_email


def validate_password_strength(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(PASSWORD_LENGTH_ERROR)


def normalize_profile_metadata(group_name: str, course: int | None) -> tuple[str | None, int | None]:
    normalized_group = normalize_bounded_text(
        group_name,
        label='Группа',
        max_length=50,
    )
    if course is not None and not 1 <= course <= 12:
        raise ValueError('Курс должен быть числом от 1 до 12.')
    return normalized_group, course


def build_password_reset_url(request: Request, token: str) -> str:
    query = urlencode({'token': token})
    if settings.public_base_url:
        return f'{settings.public_base_url}/reset-password?{query}'
    reset_path = request.url_for('reset_password_page').path
    return f'{request.base_url.scheme}://{request.base_url.netloc}{reset_path}?{query}'


def establish_user_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session['csrf_token'] = secrets.token_urlsafe(32)
    request.session['user_id'] = user.id
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()


@router.get('/', response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse('/dashboard', status_code=302)
    return templates.TemplateResponse(request, 'auth/index.html', {})


@router.get('/register', response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, 'auth/register.html', {'error': None})


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
    enforce_rate_limit(
        request,
        scope='register',
        limit=20,
        window_seconds=60 * 60,
    )
    try:
        username, email = normalize_account_identity(username, email)
        group_name, course = normalize_profile_metadata(group_name, course)
        validate_password_strength(password)
    except ValueError as error:
        return templates.TemplateResponse(
            request,
            'auth/register.html',
            {'error': str(error)},
        )

    existing = db.query(User).filter(
        (func.lower(User.username) == normalize_username_lookup(username)) | (User.email == email)
    ).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'auth/register.html',
            {'error': 'Пользователь с таким логином или email уже существует.'},
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        group_name=group_name,
        course=course,
        schedule_unit='class',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    establish_user_session(request, user)
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, 'auth/login.html', {'error': None})


@router.post('/login', response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    username = normalize_username(username)
    normalized_username = normalize_username_lookup(username)
    normalized_email = normalize_email(username)

    user = db.query(User).filter(
        (func.lower(User.username) == normalized_username) | (User.email == normalized_email)
    ).first()
    if (
        len(password) > PASSWORD_MAX_LENGTH
        or not user
        or not verify_password(password, user.password_hash)
    ):
        enforce_rate_limit(
            request,
            scope='login-ip',
            limit=40,
            window_seconds=5 * 60,
        )
        enforce_rate_limit(
            request,
            scope='login-identity',
            discriminator=normalized_username,
            limit=8,
            window_seconds=5 * 60,
        )
        return templates.TemplateResponse(
            request,
            'auth/login.html',
            {'error': 'Неверный логин или пароль.'},
        )
    auth_rate_limiter.clear(rate_limit_key(request, 'login-ip'))
    auth_rate_limiter.clear(rate_limit_key(request, 'login-identity', normalized_username))
    establish_user_session(request, user)
    return RedirectResponse('/dashboard', status_code=302)


@router.get('/forgot-password', response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        'auth/forgot_password.html',
        {'error': None, 'success': None, 'email': ''},
    )


@router.post('/forgot-password', response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(
        request,
        scope='forgot-password',
        limit=5,
        window_seconds=15 * 60,
    )
    try:
        email = validate_and_normalize_email(email)
    except ValueError as error:
        return templates.TemplateResponse(
            request,
            'auth/forgot_password.html',
            {'error': str(error), 'success': None, 'email': normalize_email(email)},
        )

    if not password_reset_enabled():
        logger.warning('Password reset requested while SMTP delivery is not configured.')
        return templates.TemplateResponse(
            request,
            'auth/forgot_password.html',
            {
                'error': None,
                'success': PASSWORD_RESET_GENERIC_SUCCESS,
                'email': email,
            },
        )

    user = db.query(User).filter(User.email == email).first()
    if user:
        reset_token = generate_password_reset_token(user)
        reset_url = build_password_reset_url(request, reset_token)
        try:
            send_password_reset_email(user.email, reset_url)
        except Exception:
            logger.exception('Password reset email delivery failed.')
            return templates.TemplateResponse(
                request,
                'auth/forgot_password.html',
                {
                    'error': None,
                    'success': PASSWORD_RESET_GENERIC_SUCCESS,
                    'email': email,
                },
            )

    return templates.TemplateResponse(
        request,
        'auth/forgot_password.html',
        {
            'error': None,
            'success': PASSWORD_RESET_GENERIC_SUCCESS,
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
        'auth/reset_password.html',
        {
            'error': None if token_valid else 'Ссылка для сброса недействительна.',
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
    enforce_rate_limit(
        request,
        scope='reset-password',
        limit=10,
        window_seconds=15 * 60,
    )
    payload = load_password_reset_payload(token)
    user = db.query(User).filter(User.id == payload.get('user_id')).first() if payload else None
    token_valid = validate_password_reset_token(token, user)

    if not token_valid:
        return templates.TemplateResponse(
            request,
            'auth/reset_password.html',
            {
                'error': 'Ссылка для сброса недействительна.',
                'success': None,
                'token': token,
                'token_valid': False,
            },
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            'auth/reset_password.html',
            {
                'error': 'Пароли не совпадают.',
                'success': None,
                'token': token,
                'token_valid': True,
            },
        )

    try:
        validate_password_strength(new_password)
    except ValueError:
        return templates.TemplateResponse(
            request,
            'auth/reset_password.html',
            {
                'error': PASSWORD_LENGTH_ERROR,
                'success': None,
                'token': token,
                'token_valid': True,
            },
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        request,
        'auth/reset_password.html',
        {
            'error': None,
            'success': 'Пароль обновлен. Теперь можно войти.',
            'token': '',
            'token_valid': False,
        },
    )


@router.post('/logout')
def logout(request: Request, _: None = Depends(validate_csrf)):
    request.session.clear()
    return RedirectResponse('/', status_code=302)
