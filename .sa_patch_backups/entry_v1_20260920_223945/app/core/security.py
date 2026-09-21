from fastapi import Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from ..models import User


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def get_current_user(request: Request, db: Session):
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()
