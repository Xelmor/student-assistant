from __future__ import annotations

import smtplib
from email.message import EmailMessage

from itsdangerous import BadSignature, BadTimeSignature, SignatureExpired, URLSafeTimedSerializer

from ..core.config import settings
from ..models import User


TOKEN_SALT = 'password-reset'


def password_reset_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def get_password_reset_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=TOKEN_SALT)


def generate_password_reset_token(user: User) -> str:
    serializer = get_password_reset_serializer()
    return serializer.dumps({'user_id': user.id, 'password_hash': user.password_hash})


def validate_password_reset_token(token: str, user: User | None) -> bool:
    if not token or user is None:
        return False

    serializer = get_password_reset_serializer()
    try:
        payload = serializer.loads(token, max_age=settings.password_reset_token_ttl_seconds)
    except (BadSignature, BadTimeSignature, SignatureExpired):
        return False

    return payload.get('user_id') == user.id and payload.get('password_hash') == user.password_hash


def load_password_reset_payload(token: str) -> dict | None:
    serializer = get_password_reset_serializer()
    try:
        payload = serializer.loads(token, max_age=settings.password_reset_token_ttl_seconds)
    except (BadSignature, BadTimeSignature, SignatureExpired):
        return None
    return payload if isinstance(payload, dict) else None


def send_password_reset_email(email_to: str, reset_url: str) -> None:
    message = EmailMessage()
    message['Subject'] = 'Восстановление пароля'
    message['From'] = (
        f'{settings.smtp_from_name} <{settings.smtp_from_email}>'
        if settings.smtp_from_name
        else settings.smtp_from_email
    )
    message['To'] = email_to
    message.set_content(
        'Вы запросили восстановление пароля.\n\n'
        f'Перейдите по ссылке, чтобы задать новый пароль:\n{reset_url}\n\n'
        f'Ссылка действует {settings.password_reset_token_ttl_seconds // 60} минут.\n'
        'Если вы не запрашивали смену пароля, просто проигнорируйте это письмо.\n'
    )

    smtp_client = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_client(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if not settings.smtp_ssl and settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
