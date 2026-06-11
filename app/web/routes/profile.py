from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import User
from .auth import normalize_account_identity, normalize_profile_metadata, normalize_username_lookup
from ..dependencies import (
    SCHEDULE_UNIT_OPTIONS,
    is_local_private_data_enabled,
    require_user,
    templates,
    validate_csrf,
)

router = APIRouter()

def _build_profile_context(
    request: Request,
    user: User,
    *,
    error=None,
    success=None,
    data_success=None,
    data_error=None,
):
    return {
        'user': user,
        'error': error,
        'success': success,
        'local_private_data_available': is_local_private_data_enabled(request),
        'data_success': data_success,
        'data_error': data_error,
        'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
    }


@router.get('/profile', response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    data_success = request.query_params.get('data_success')
    data_error = request.query_params.get('data_error')
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    return templates.TemplateResponse(
        request,
        'profile/profile.html',
        _build_profile_context(
            request,
            user,
            data_success=data_success,
            data_error=data_error,
        ),
    )


@router.post('/profile', response_class=HTMLResponse)
def update_profile(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    group_name: str = Form(''),
    course: int | None = Form(None),
    schedule_unit: str = Form('class'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    try:
        normalized_username, normalized_email = normalize_account_identity(username, email)
        normalized_group_name, normalized_course = normalize_profile_metadata(group_name, course)
    except ValueError as error:
        return templates.TemplateResponse(
            request,
            'profile/profile.html',
            _build_profile_context(request, user, error=str(error)),
        )

    existing = db.query(User).filter(
        (
            (func.lower(User.username) == normalize_username_lookup(normalized_username))
            | (User.email == normalized_email)
        )
        & (User.id != user.id)
    ).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'profile/profile.html',
            _build_profile_context(
                request,
                user,
                error='Пользователь с таким логином или email уже существует.',
            ),
        )

    if schedule_unit not in SCHEDULE_UNIT_OPTIONS:
        schedule_unit = 'class'

    user.username = normalized_username
    user.email = normalized_email
    user.group_name = normalized_group_name
    user.course = normalized_course
    user.schedule_unit = schedule_unit
    db.commit()
    db.refresh(user)
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()

    return templates.TemplateResponse(
        request,
        'profile/profile.html',
        _build_profile_context(request, user, success='Профиль обновлен.'),
    )


@router.get('/local-profile', response_class=HTMLResponse)
def local_profile_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if not is_local_private_data_enabled(request):
        return RedirectResponse('/dashboard', status_code=302)

    return templates.TemplateResponse(
        request,
        'profile/local_profile.html',
        {
            'user': user,
        },
    )
