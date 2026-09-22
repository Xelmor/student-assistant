from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import get_db
from ...core.rate_limit import auth_rate_limiter, enforce_rate_limit, rate_limit_key
from ...core.security import LOCAL_PROFILE_COOKIE, establish_user_session
from ...core.time import current_time
from ...core.validation import normalize_bounded_text
from ...models import WorkspaceDevice
from ...services.workspace_sync import (
    LINK_TTL_MINUTES,
    consume_link_session,
    ensure_workspace,
    get_active_link_session,
    infer_device_name,
    issue_link_session,
    normalize_pairing_code,
    qr_svg_data_uri,
    recover_workspace,
    rotate_recovery_key,
)
from ..dependencies import require_user, templates, validate_csrf


router = APIRouter()


def _protect_secret_response(response):
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _set_device_cookie(response, raw_token: str) -> None:
    response.set_cookie(
        LOCAL_PROFILE_COOKIE,
        raw_token,
        max_age=365 * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite='lax',
        path='/',
    )


def _device_name(request: Request, value: str) -> str:
    normalized = normalize_bounded_text(
        value,
        label='Название устройства',
        max_length=80,
    )
    return normalized or infer_device_name(request.headers.get('user-agent'))


def _connect_context(
    request: Request,
    *,
    mode: str,
    error: str | None = None,
    token: str = '',
    token_valid: bool = False,
    code: str = '',
    recovery_key: str = '',
):
    return {
        'mode': mode,
        'error': error,
        'link_token': token,
        'link_token_valid': token_valid,
        'code': code,
        'recovery_key': recovery_key,
        'default_device_name': infer_device_name(request.headers.get('user-agent')),
    }


def _current_device(request: Request, db: Session, workspace_id: int):
    device_row_id = request.session.get('workspace_device_id')
    if not device_row_id:
        return None
    return db.query(WorkspaceDevice).filter(
        WorkspaceDevice.id == device_row_id,
        WorkspaceDevice.workspace_id == workspace_id,
        WorkspaceDevice.revoked_at.is_(None),
    ).first()


@router.get('/connect-device', response_class=HTMLResponse)
def connect_device_page(request: Request):
    return _protect_secret_response(templates.TemplateResponse(
        request,
        'auth/connect_device.html',
        _connect_context(request, mode='code'),
    ))


@router.get('/link-device', response_class=HTMLResponse, name='link_device_page')
def link_device_page(
    request: Request,
    token: str = Query(''),
    db: Session = Depends(get_db),
):
    link_session = get_active_link_session(db, token=token) if token else None
    return _protect_secret_response(templates.TemplateResponse(
        request,
        'auth/connect_device.html',
        _connect_context(
            request,
            mode='token',
            token=token if link_session else '',
            token_valid=bool(link_session),
            error=None if link_session else 'Ссылка подключения недействительна или уже истекла.',
        ),
        status_code=200 if link_session else 400,
    ))


@router.get('/recover', response_class=HTMLResponse)
def recover_page(request: Request):
    return _protect_secret_response(templates.TemplateResponse(
        request,
        'auth/connect_device.html',
        _connect_context(request, mode='recovery'),
    ))


@router.post('/connect-device/code')
def connect_device_by_code(
    request: Request,
    code: str = Form(...),
    device_name: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    normalized_code = normalize_pairing_code(code)
    enforce_rate_limit(request, scope='device-link-ip', limit=12, window_seconds=5 * 60)
    enforce_rate_limit(
        request,
        scope='device-link-code',
        discriminator=normalized_code,
        limit=6,
        window_seconds=5 * 60,
    )
    result = consume_link_session(
        db,
        code=normalized_code,
        device_name=_device_name(request, device_name),
        user_agent=request.headers.get('user-agent'),
    )
    if not result:
        db.rollback()
        return _protect_secret_response(templates.TemplateResponse(
            request,
            'auth/connect_device.html',
            _connect_context(
                request,
                mode='code',
                code=normalized_code,
                error='Неверный, использованный или просроченный код подключения.',
            ),
            status_code=400,
        ))
    user, device, raw_token = result
    db.commit()
    establish_user_session(request, user, device)
    auth_rate_limiter.clear(rate_limit_key(request, 'device-link-code', normalized_code))
    response = RedirectResponse('/dashboard?device_connected=1', status_code=302)
    _set_device_cookie(response, raw_token)
    return response


@router.post('/link-device/confirm')
def connect_device_by_token(
    request: Request,
    token: str = Form(...),
    device_name: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request, scope='device-link-token', limit=12, window_seconds=5 * 60)
    result = consume_link_session(
        db,
        token=token,
        device_name=_device_name(request, device_name),
        user_agent=request.headers.get('user-agent'),
    )
    if not result:
        db.rollback()
        return _protect_secret_response(templates.TemplateResponse(
            request,
            'auth/connect_device.html',
            _connect_context(
                request,
                mode='token',
                error='Ссылка подключения недействительна, использована или истекла.',
            ),
            status_code=400,
        ))
    user, device, raw_token = result
    db.commit()
    establish_user_session(request, user, device)
    response = RedirectResponse('/dashboard?device_connected=1', status_code=302)
    _set_device_cookie(response, raw_token)
    return response


@router.post('/recover')
def recover_with_key(
    request: Request,
    recovery_key: str = Form(...),
    device_name: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request, scope='workspace-recovery-ip', limit=6, window_seconds=15 * 60)
    result = recover_workspace(
        db,
        recovery_key=recovery_key,
        device_name=_device_name(request, device_name),
        user_agent=request.headers.get('user-agent'),
    )
    if not result:
        db.rollback()
        return _protect_secret_response(templates.TemplateResponse(
            request,
            'auth/connect_device.html',
            _connect_context(
                request,
                mode='recovery',
                recovery_key=recovery_key,
                error='Ключ восстановления не найден. Проверьте символы и попробуйте снова.',
            ),
            status_code=400,
        ))
    user, device, raw_token = result
    db.commit()
    establish_user_session(request, user, device)
    response = RedirectResponse('/dashboard?recovered=1', status_code=302)
    _set_device_cookie(response, raw_token)
    return response


@router.post(
    '/profile/devices/link-session',
    response_class=JSONResponse,
    name='create_device_link_session',
)
def create_device_link_session(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return JSONResponse({'error': 'Требуется вход.'}, status_code=401)
    enforce_rate_limit(request, scope='device-link-create', limit=10, window_seconds=15 * 60)
    workspace = ensure_workspace(db, user)
    current_device = _current_device(request, db, workspace.id)
    raw_current_token = None
    if not current_device:
        from ...services.workspace_sync import create_device

        current_device, raw_current_token = create_device(
            db,
            workspace,
            device_name=infer_device_name(request.headers.get('user-agent')),
            user_agent=request.headers.get('user-agent'),
        )
        establish_user_session(request, user, current_device)

    link_session, code, raw_link_token = issue_link_session(
        db,
        workspace,
        created_by_device=current_device,
    )
    db.commit()
    link_route = request.url_for('link_device_page')
    if settings.public_base_url:
        link_url = (
            f'{settings.public_base_url}{link_route.path}?'
            f'{urlencode({"token": raw_link_token})}'
        )
    else:
        link_url = str(link_route.include_query_params(token=raw_link_token))
    response = JSONResponse(
        {
            'code': code,
            'formatted_code': f'{code[:3]} {code[3:]}',
            'expires_at': link_session.expires_at.isoformat(),
            'expires_in_seconds': LINK_TTL_MINUTES * 60,
            'link_url': link_url,
            'qr_data_uri': qr_svg_data_uri(link_url),
        }
    )
    _protect_secret_response(response)
    if raw_current_token:
        _set_device_cookie(response, raw_current_token)
    return response


@router.post('/profile/devices/{device_id}/revoke')
def revoke_device(
    device_id: int,
    request: Request,
    confirm_current: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/', status_code=302)
    workspace = ensure_workspace(db, user)
    device = db.query(WorkspaceDevice).filter(
        WorkspaceDevice.id == device_id,
        WorkspaceDevice.workspace_id == workspace.id,
        WorkspaceDevice.revoked_at.is_(None),
    ).first()
    if not device:
        return RedirectResponse('/profile?device_error=not-found#profile-devices', status_code=302)

    is_current = request.session.get('workspace_device_id') == device.id
    if is_current and confirm_current != 'ОТКЛЮЧИТЬ':
        return RedirectResponse('/profile?device_error=confirm-current#profile-devices', status_code=302)

    device.revoked_at = current_time()
    db.commit()
    if is_current:
        request.session.clear()
        response = RedirectResponse('/?device_revoked=1', status_code=302)
        response.delete_cookie(
            LOCAL_PROFILE_COOKIE,
            path='/',
            httponly=True,
            secure=settings.cookie_secure,
            samesite='lax',
        )
        return response
    return RedirectResponse('/profile?device_status=revoked#profile-devices', status_code=302)


@router.post('/profile/recovery-key/rotate', response_class=HTMLResponse)
def rotate_workspace_recovery_key(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/', status_code=302)
    enforce_rate_limit(request, scope='recovery-key-rotate', limit=5, window_seconds=60 * 60)
    workspace = ensure_workspace(db, user)
    recovery_key = rotate_recovery_key(workspace)
    db.commit()
    return _protect_secret_response(templates.TemplateResponse(
        request,
        'auth/recovery_key.html',
        {
            'recovery_key': recovery_key,
            'is_initial': False,
            'continue_href': '/profile#profile-devices',
        },
    ))
