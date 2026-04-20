from __future__ import annotations

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import User


def ensure_bot_api_enabled():
    if not settings.telegram_bot_api_token:
        raise HTTPException(status_code=503, detail='Telegram bot API token is not configured.')


def require_bot_token(x_bot_api_token: str = Header(default='')):
    ensure_bot_api_enabled()
    if x_bot_api_token != settings.telegram_bot_api_token:
        raise HTTPException(status_code=401, detail='Invalid bot API token.')


def get_user_by_chat_id(db: Session, chat_id: int) -> User:
    user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if not user:
        raise HTTPException(status_code=404, detail='Telegram account is not linked.')
    return user

