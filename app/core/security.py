import hashlib
import secrets

from fastapi import Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from ..models import User


password_hash = PasswordHash.recommended()
LOCAL_PROFILE_COOKIE = 'sa_device_profile'


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def hash_local_profile_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _establish_restored_session(request: Request, user: User) -> None:
    display_name = user.display_name or user.username
    request.session.clear()
    request.session['csrf_token'] = secrets.token_urlsafe(32)
    request.session['user_id'] = user.id
    request.session['username'] = display_name
    request.session['username_initial'] = (display_name[:1] or 'U').upper()


def get_current_user(request: Request, db: Session):
    user_id = request.session.get('user_id')
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user
        request.session.clear()

    token = request.cookies.get(LOCAL_PROFILE_COOKIE, '').strip()
    if not token:
        return None

    token_hash = hash_local_profile_token(token)
    user = (
        db.query(User)
        .filter(
            User.is_local_profile.is_(True),
            User.local_access_token_hash == token_hash,
        )
        .first()
    )
    if not user:
        return None

    _establish_restored_session(request, user)
    return user
