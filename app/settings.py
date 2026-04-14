from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


INSECURE_SECRET_KEYS = {
    '',
    'changeme',
    'change_me',
    'dev_secret_change_me',
    'dev_local_secret_change_me',
    'secret',
}


def env_flag(name: str, default: str = 'false') -> bool:
    from os import getenv

    return getenv(name, default).strip().lower() == 'true'


def normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith('postgres://'):
        return f"postgresql+psycopg://{normalized[len('postgres://'):]}"
    if normalized.startswith('postgresql://'):
        return f"postgresql+psycopg://{normalized[len('postgresql://'):]}"
    return normalized


@dataclass(frozen=True)
class Settings:
    app_env: str
    secret_key: str
    cookie_secure: bool
    database_url: str
    timezone: str
    host: str
    port: int
    reload: bool
    allow_local_private_data: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_from_name: str
    smtp_starttls: bool
    smtp_ssl: bool
    password_reset_token_ttl_seconds: int
    openai_api_key: str
    openai_model: str
    openai_timeout_seconds: int
    ai_input_max_length: int
    base_dir: Path


def get_settings() -> Settings:
    from os import getenv

    app_env = (getenv('APP_ENV') or 'development').strip().lower()
    secret_key = (getenv('SECRET_KEY') or '').strip()
    cookie_secure = env_flag('COOKIE_SECURE')

    if len(secret_key) < 32 or secret_key.lower() in INSECURE_SECRET_KEYS:
        raise RuntimeError(
            'SECRET_KEY must be set to a unique random string with at least 32 characters.'
        )

    if app_env == 'production' and not cookie_secure:
        raise RuntimeError('COOKIE_SECURE must be true when APP_ENV=production.')

    return Settings(
        app_env=app_env,
        secret_key=secret_key,
        cookie_secure=cookie_secure,
        database_url=normalize_database_url(getenv('DATABASE_URL', 'sqlite:///./student_assistant.db')),
        timezone=(getenv('APP_TIMEZONE') or 'Europe/Moscow').strip() or 'Europe/Moscow',
        host=getenv('HOST', '0.0.0.0'),
        port=int(getenv('PORT', '8000')),
        reload=env_flag('RELOAD'),
        allow_local_private_data=env_flag('ALLOW_LOCAL_PRIVATE_DATA'),
        smtp_host=(getenv('SMTP_HOST') or '').strip(),
        smtp_port=int(getenv('SMTP_PORT', '587')),
        smtp_username=(getenv('SMTP_USERNAME') or '').strip(),
        smtp_password=(getenv('SMTP_PASSWORD') or '').strip(),
        smtp_from_email=(getenv('SMTP_FROM_EMAIL') or '').strip(),
        smtp_from_name=(getenv('SMTP_FROM_NAME') or 'Student Assistant').strip(),
        smtp_starttls=env_flag('SMTP_STARTTLS', 'true'),
        smtp_ssl=env_flag('SMTP_SSL'),
        password_reset_token_ttl_seconds=int(getenv('PASSWORD_RESET_TOKEN_TTL_SECONDS', '3600')),
        openai_api_key=(getenv('OPENAI_API_KEY') or '').strip(),
        openai_model=(getenv('OPENAI_MODEL') or 'gpt-5-mini').strip() or 'gpt-5-mini',
        openai_timeout_seconds=int(getenv('OPENAI_TIMEOUT_SECONDS', '30')),
        ai_input_max_length=max(500, int(getenv('AI_INPUT_MAX_LENGTH', '2500'))),
        base_dir=Path(__file__).resolve().parent,
    )


settings = get_settings()
