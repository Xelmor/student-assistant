from datetime import datetime
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import get_db
from ...core.time import current_time
from ...core.validation import normalize_bounded_text
from ...models import User
from ...services.telegram_bot import (
    TelegramAPIError,
    TelegramReply,
    generate_link_code,
    get_active_link_code,
    send_telegram_message,
    unlink_telegram_user,
)
from ...services.telegram_digest import build_morning_digest_message
from ...services.telegram_notifications import VALID_DEADLINE_REMINDER_HOURS
from ...services.workspace_sync import ensure_workspace
from .auth import normalize_account_identity, normalize_profile_metadata, normalize_username_lookup
from ..dependencies import (
    SCHEDULE_UNIT_OPTIONS,
    is_local_private_data_enabled,
    require_user,
    templates,
    validate_csrf,
)

router = APIRouter()
logger = logging.getLogger(__name__)
TELEGRAM_DIGEST_TIMEZONES = (
    'Europe/Moscow',
    'Europe/Kaliningrad',
    'Europe/Samara',
    'Asia/Yekaterinburg',
    'Asia/Omsk',
    'Asia/Novosibirsk',
    'Asia/Irkutsk',
    'Asia/Yakutsk',
    'Asia/Vladivostok',
    'Asia/Magadan',
    'Asia/Kamchatka',
    'UTC',
)


def _device_activity_label(last_seen_at: datetime) -> str:
    seconds = max(0, int((current_time() - last_seen_at).total_seconds()))
    if seconds < 90:
        return 'Сейчас'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes} мин. назад'
    hours = minutes // 60
    if hours < 24:
        return f'{hours} ч. назад'
    days = hours // 24
    if days == 1:
        return 'Вчера'
    return f'{days} дн. назад'

def _build_profile_context(
    request: Request,
    user: User,
    *,
    error=None,
    success=None,
    data_success=None,
    data_error=None,
    telegram_status=None,
    device_status=None,
    device_error=None,
):
    workspace = user.workspace
    devices = []
    if workspace:
        devices = [
            {
                'record': device,
                'activity_label': _device_activity_label(device.last_seen_at),
            }
            for device in sorted(
                (item for item in workspace.devices if item.revoked_at is None),
                key=lambda item: item.last_seen_at,
                reverse=True,
            )
        ]
    return {
        'user': user,
        'error': error,
        'success': success,
        'local_private_data_available': is_local_private_data_enabled(request),
        'data_success': data_success,
        'data_error': data_error,
        'schedule_unit_options': SCHEDULE_UNIT_OPTIONS,
        'telegram_status': telegram_status,
        'telegram_link_code': get_active_link_code(user),
        'telegram_link_code_ttl_minutes': settings.telegram_link_code_ttl_minutes,
        'telegram_digest_timezones': TELEGRAM_DIGEST_TIMEZONES,
        'telegram_digest_default_timezone': settings.timezone,
        'telegram_bot_url': (
            f'https://t.me/{settings.telegram_bot_username}'
            if settings.telegram_bot_username
            else None
        ),
        'telegram_deadline_reminder_hours_options': VALID_DEADLINE_REMINDER_HOURS,
        'workspace': workspace,
        'workspace_devices': devices,
        'current_workspace_device_id': request.session.get('workspace_device_id'),
        'device_status': device_status,
        'device_error': device_error,
    }


@router.get('/profile', response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    data_success = request.query_params.get('data_success')
    data_error = request.query_params.get('data_error')
    telegram_status = request.query_params.get('telegram_status')
    device_status = request.query_params.get('device_status')
    device_error = request.query_params.get('device_error')
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if not user.workspace:
        ensure_workspace(db, user)
        db.commit()
        db.refresh(user)

    return templates.TemplateResponse(
        request,
        'profile/profile.html',
        _build_profile_context(
            request,
            user,
            data_success=data_success,
            data_error=data_error,
            telegram_status=telegram_status,
            device_status=device_status,
            device_error=device_error,
        ),
    )


@router.post('/profile', response_class=HTMLResponse)
def update_profile(
    request: Request,
    username: str = Form(''),
    email: str = Form(''),
    display_name: str = Form(''),
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
        normalized_display_name = normalize_bounded_text(
            display_name,
            label='Имя',
            max_length=40,
        )
        normalized_group_name, normalized_course = normalize_profile_metadata(group_name, course)
        if user.is_local_profile:
            normalized_username = user.username
            normalized_email = user.email
        else:
            normalized_username, normalized_email = normalize_account_identity(username, email)
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
    user.display_name = normalized_display_name
    user.group_name = normalized_group_name
    user.course = normalized_course
    user.schedule_unit = schedule_unit
    db.commit()
    db.refresh(user)
    session_name = user.display_name or user.username
    request.session['username'] = session_name
    request.session['username_initial'] = (session_name[:1] or 'U').upper()

    return templates.TemplateResponse(
        request,
        'profile/profile.html',
        _build_profile_context(request, user, success='Профиль обновлен.'),
    )


@router.post('/profile/telegram/link-code')
def create_telegram_link_code(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    if user.telegram_user_id is not None:
        return RedirectResponse(
            '/profile?telegram_status=already-linked#profile-telegram',
            status_code=302,
        )

    try:
        generate_link_code(db, user)
    except RuntimeError:
        return RedirectResponse(
            '/profile?telegram_status=code-error#profile-telegram',
            status_code=302,
        )
    return RedirectResponse(
        '/profile?telegram_status=code-created#profile-telegram',
        status_code=302,
    )


@router.post('/profile/telegram/unlink')
def unlink_telegram(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    unlink_telegram_user(db, user)
    return RedirectResponse('/profile#profile-telegram', status_code=302)


@router.post('/profile/telegram/digest-settings')
def update_telegram_digest_settings(
    request: Request,
    digest_enabled: str | None = Form(None),
    digest_time: str = Form('08:00'),
    digest_timezone: str = Form('Europe/Moscow'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    if user.telegram_user_id is None or user.telegram_chat_id is None:
        return RedirectResponse(
            '/profile?telegram_status=digest-not-linked#profile-telegram',
            status_code=302,
        )

    try:
        parsed_time = datetime.strptime(digest_time, '%H:%M').time()
        ZoneInfo(digest_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return RedirectResponse(
            '/profile?telegram_status=digest-error#profile-telegram',
            status_code=302,
        )

    user.telegram_morning_digest_enabled = digest_enabled is not None
    user.telegram_morning_digest_time = parsed_time
    user.telegram_morning_digest_timezone = digest_timezone
    db.commit()
    return RedirectResponse(
        '/profile?telegram_status=digest-saved#profile-telegram',
        status_code=302,
    )


@router.post('/profile/telegram/notification-settings')
def update_telegram_notification_settings(
    request: Request,
    digest_enabled: str | None = Form(None),
    digest_time: str = Form('08:00'),
    digest_timezone: str = Form('Europe/Moscow'),
    deadline_enabled: str | None = Form(None),
    deadline_hours: int = Form(24),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    if user.telegram_user_id is None or user.telegram_chat_id is None:
        return RedirectResponse(
            '/profile?telegram_status=notifications-not-linked#profile-telegram',
            status_code=302,
        )

    try:
        parsed_time = datetime.strptime(digest_time, '%H:%M').time()
        ZoneInfo(digest_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return RedirectResponse(
            '/profile?telegram_status=notifications-error#profile-telegram',
            status_code=302,
        )
    if deadline_hours not in VALID_DEADLINE_REMINDER_HOURS:
        return RedirectResponse(
            '/profile?telegram_status=notifications-error#profile-telegram',
            status_code=302,
        )

    user.telegram_morning_digest_enabled = digest_enabled is not None
    user.telegram_morning_digest_time = parsed_time
    user.telegram_morning_digest_timezone = digest_timezone
    user.telegram_deadline_reminders_enabled = deadline_enabled is not None
    user.telegram_deadline_reminder_hours = deadline_hours
    db.commit()
    return RedirectResponse(
        '/profile?telegram_status=notifications-saved#profile-telegram',
        status_code=302,
    )


@router.post('/profile/telegram/digest-test')
def send_telegram_digest_test(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    if user.telegram_user_id is None or user.telegram_chat_id is None:
        return RedirectResponse(
            '/profile?telegram_status=digest-not-linked#profile-telegram',
            status_code=302,
        )

    try:
        send_telegram_message(
            TelegramReply(
                chat_id=user.telegram_chat_id,
                text=build_morning_digest_message(db, user),
            )
        )
    except TelegramAPIError:
        return RedirectResponse(
            '/profile?telegram_status=digest-test-error#profile-telegram',
            status_code=302,
        )
    except Exception:
        logger.exception('Telegram digest test send failed for user id %s.', user.id)
        return RedirectResponse(
            '/profile?telegram_status=digest-test-error#profile-telegram',
            status_code=302,
        )

    return RedirectResponse(
        '/profile?telegram_status=digest-test-sent#profile-telegram',
        status_code=302,
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
