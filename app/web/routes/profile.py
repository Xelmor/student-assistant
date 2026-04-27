from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import User
from ..dependencies import (
    SCHEDULE_UNIT_OPTIONS,
    is_local_private_data_enabled,
    require_user,
    templates,
    validate_csrf,
)

router = APIRouter()


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
        {
            'user': user,
            'error': None,
            'success': None,
            'local_private_data_available': is_local_private_data_enabled(request),
            'data_success': data_success,
            'data_error': data_error,
            'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
        },
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

    existing = db.query(User).filter(
        ((User.username == username) | (User.email == email)) & (User.id != user.id)
    ).first()
    if existing:
        return templates.TemplateResponse(
            request,
            'profile/profile.html',
            {
                'user': user,
                'error': 'РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ СЃ С‚Р°РєРёРј Р»РѕРіРёРЅРѕРј РёР»Рё email СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓРµС‚.',
                'success': None,
                'local_private_data_available': is_local_private_data_enabled(request),
                'data_success': None,
                'data_error': None,
                'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
            },
        )

    if schedule_unit not in SCHEDULE_UNIT_OPTIONS:
        schedule_unit = 'class'

    user.username = username
    user.email = email
    user.group_name = group_name or None
    user.course = course
    user.schedule_unit = schedule_unit
    db.commit()
    db.refresh(user)
    request.session['username'] = user.username
    request.session['username_initial'] = (user.username[:1] or 'U').upper()

    return templates.TemplateResponse(
        request,
        'profile/profile.html',
        {
            'user': user,
            'error': None,
            'success': 'РџСЂРѕС„РёР»СЊ РѕР±РЅРѕРІР»РµРЅ.',
            'local_private_data_available': is_local_private_data_enabled(request),
            'data_success': None,
            'data_error': None,
            'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
        },
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
