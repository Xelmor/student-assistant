import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from ..core.time import current_time
from ..models import User, WorkspaceDevice


password_hash = PasswordHash.recommended()
LOCAL_PROFILE_COOKIE = 'sa_device_profile'


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def hash_local_profile_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def establish_user_session(
    request: Request,
    user: User,
    device: WorkspaceDevice | None = None,
) -> None:
    display_name = user.display_name or user.username
    request.session.clear()
    request.session['csrf_token'] = secrets.token_urlsafe(32)
    request.session['user_id'] = user.id
    request.session['username'] = display_name
    request.session['username_initial'] = (display_name[:1] or 'U').upper()
    if device is not None:
        request.session['workspace_device_id'] = device.id


def _active_session_device(request: Request, db: Session, user: User):
    device_row_id = request.session.get('workspace_device_id')
    if not device_row_id:
        return None
    device = (
        db.query(WorkspaceDevice)
        .join(WorkspaceDevice.workspace)
        .filter(
            WorkspaceDevice.id == device_row_id,
            WorkspaceDevice.revoked_at.is_(None),
            WorkspaceDevice.workspace.has(user_id=user.id, is_active=True),
        )
        .first()
    )
    if device and device.last_seen_at < current_time() - timedelta(minutes=1):
        device.last_seen_at = current_time()
        db.commit()
    return device


def _device_from_cookie(request: Request, db: Session):
    token = request.cookies.get(LOCAL_PROFILE_COOKIE, '').strip()
    if not token:
        return None
    from ..services.workspace_sync import hash_device_token

    candidate_hashes = (hash_device_token(token), hash_local_profile_token(token))
    return (
        db.query(WorkspaceDevice)
        .filter(
            WorkspaceDevice.token_hash.in_(candidate_hashes),
            WorkspaceDevice.revoked_at.is_(None),
            WorkspaceDevice.workspace.has(is_active=True),
        )
        .first()
    )


def get_current_user(request: Request, db: Session):
    user_id = request.session.get('user_id')
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            if request.session.get('workspace_device_id'):
                device = _active_session_device(request, db, user)
                if device:
                    return user
                request.session.clear()
                raise HTTPException(status_code=302, headers={'Location': '/'})
            elif not user.is_local_profile:
                # Password-based accounts created before device sync keep their
                # existing session until they opt into a device connection.
                return user
            else:
                cookie_device = _device_from_cookie(request, db)
                if cookie_device and cookie_device.workspace.user_id == user.id:
                    establish_user_session(request, user, cookie_device)
                    return user
        request.session.clear()

    device = _device_from_cookie(request, db)
    if device:
        user = device.workspace.user
        establish_user_session(request, user, device)
        return user

    # Legacy local profiles are backfilled into WorkspaceDevice by the startup
    # migration. Never recreate a device from the old user-level hash here:
    # doing so could accidentally reactivate a revoked device.
    return None
