from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import urlparse

from dotenv import load_dotenv


load_dotenv()


INSECURE_SECRET_KEYS = {
    '',
    'changeme',
    'change_me',
    'dev_secret_change_me',
    'dev_local_secret_change_me',
    'replace_with_a_unique_random_string_at_least_32_chars_long',
    '<long-random-secret-at-least-32-chars>',
    'secret',
}

DEVELOPMENT_SECRET_KEY = token_urlsafe(48)
DEFAULT_SQLITE_PATH = './data/student_assistant.db'


def env_flag(name: str, default: str = 'false') -> bool:
    from os import getenv

    return getenv(name, default).strip().lower() == 'true'


def parse_allowed_hosts(raw_value: str) -> tuple[str, ...]:
    return tuple(host.strip().lower() for host in raw_value.split(',') if host.strip())


def merge_allowed_hosts(*host_groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    merged = []
    seen = set()
    for group in host_groups:
        for host in group:
            normalized = host.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged.append(normalized)
    return tuple(merged)


def normalize_public_base_url(raw_value: str) -> str:
    value = raw_value.strip().rstrip('/')
    if not value:
        return ''

    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path not in {'', '/'}:
        raise RuntimeError('PUBLIC_BASE_URL must be an absolute http(s) origin without a path.')
    return value


def normalize_telegram_webhook_path(raw_value: str) -> str:
    value = raw_value.strip() or '/telegram/webhook'
    if not value.startswith('/'):
        value = f'/{value}'
    value = value.rstrip('/')
    if not value or '?' in value or '#' in value or '..' in value:
        raise RuntimeError('TELEGRAM_WEBHOOK_PATH must be a safe URL path.')
    return value


def normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith('postgres://'):
        return f"postgresql+psycopg://{normalized[len('postgres://'):]}"
    if normalized.startswith('postgresql://'):
        return f"postgresql+psycopg://{normalized[len('postgresql://'):]}"
    return normalized


def prepare_database_url(url: str, base_dir: Path) -> str:
    normalized = normalize_database_url(url)
    sqlite_prefix = 'sqlite:///'

    if not normalized.startswith(sqlite_prefix):
        return normalized

    sqlite_target = normalized[len(sqlite_prefix):]
    if sqlite_target.startswith('./'):
        sqlite_path = (base_dir.parent / sqlite_target[2:]).resolve()
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f'{sqlite_prefix}{sqlite_path.as_posix()}'

    sqlite_path = Path(sqlite_target)
    if sqlite_path.is_absolute():
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f'{sqlite_prefix}{sqlite_path.as_posix()}'

    sqlite_path = (base_dir.parent / sqlite_path).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f'{sqlite_prefix}{sqlite_path.as_posix()}'


@dataclass(frozen=True)
class Settings:
    app_env: str
    testing: bool
    secret_key: str
    cookie_secure: bool
    session_max_age_seconds: int
    database_url: str
    timezone: str
    host: str
    allowed_hosts: tuple[str, ...]
    public_base_url: str
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
    telegram_bot_token: str = field(repr=False)
    telegram_bot_api_base_url: str
    telegram_link_code_ttl_minutes: int
    telegram_use_webhook: bool
    telegram_webhook_base_url: str
    telegram_webhook_path: str
    telegram_webhook_secret: str = field(repr=False)
    telegram_bot_host: str
    telegram_bot_port: int
    telegram_bot_log_level: str
    telegram_bot_username: str
    telegram_digest_check_interval_seconds: int
    disable_telegram: bool
    base_dir: Path


def get_settings() -> Settings:
    from os import getenv

    base_dir = Path(__file__).resolve().parent.parent
    app_env = (getenv('APP_ENV') or 'development').strip().lower()
    testing = env_flag('TESTING') or app_env == 'test'
    disable_telegram = env_flag('DISABLE_TELEGRAM') or testing
    secret_key = (getenv('SECRET_KEY') or '').strip()
    cookie_secure = env_flag('COOKIE_SECURE')
    session_max_age_seconds = int(getenv('SESSION_MAX_AGE_SECONDS', '43200'))
    telegram_link_code_ttl_minutes = int(getenv('TELEGRAM_LINK_CODE_TTL_MINUTES', '10'))
    telegram_bot_port = int(getenv('TELEGRAM_BOT_PORT', '8001'))
    telegram_digest_check_interval_seconds = int(
        getenv('TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS', '60')
    )

    if len(secret_key) < 32 or secret_key.lower() in INSECURE_SECRET_KEYS:
        if app_env == 'production':
            raise RuntimeError(
                'SECRET_KEY must be set to a unique random string with at least 32 characters.'
            )
        secret_key = DEVELOPMENT_SECRET_KEY

    if app_env == 'production' and not cookie_secure:
        raise RuntimeError('COOKIE_SECURE must be true when APP_ENV=production.')
    if not 300 <= session_max_age_seconds <= 30 * 24 * 60 * 60:
        raise RuntimeError('SESSION_MAX_AGE_SECONDS must be between 300 and 2592000.')
    if not 1 <= telegram_link_code_ttl_minutes <= 24 * 60:
        raise RuntimeError('TELEGRAM_LINK_CODE_TTL_MINUTES must be between 1 and 1440.')
    if not 1 <= telegram_bot_port <= 65535:
        raise RuntimeError('TELEGRAM_BOT_PORT must be between 1 and 65535.')
    if not 10 <= telegram_digest_check_interval_seconds <= 3600:
        raise RuntimeError(
            'TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS must be between 10 and 3600.'
        )

    database_url = prepare_database_url(
        getenv('DATABASE_URL', f'sqlite:///{DEFAULT_SQLITE_PATH}'),
        base_dir,
    )
    host = (getenv('HOST') or '127.0.0.1').strip() or '127.0.0.1'
    public_base_url = normalize_public_base_url(getenv('PUBLIC_BASE_URL', ''))
    configured_allowed_hosts = parse_allowed_hosts(getenv('ALLOWED_HOSTS', ''))
    public_hostname = (urlparse(public_base_url).hostname or '').lower()
    render_hostname = (getenv('RENDER_EXTERNAL_HOSTNAME') or '').strip().lower()

    derived_allowed_hosts = [public_hostname, render_hostname]
    if app_env != 'production':
        derived_allowed_hosts.extend(
            ['localhost', '127.0.0.1', '0.0.0.0', '::1', 'testserver', host]
        )
    allowed_hosts = merge_allowed_hosts(configured_allowed_hosts, derived_allowed_hosts)

    if app_env == 'production':
        if '*' in allowed_hosts:
            raise RuntimeError('ALLOWED_HOSTS must not contain * when APP_ENV=production.')
        if not allowed_hosts:
            raise RuntimeError(
                'Set ALLOWED_HOSTS, PUBLIC_BASE_URL, or RENDER_EXTERNAL_HOSTNAME '
                'to the exact production hostname.'
            )
        if public_base_url and not public_base_url.startswith('https://'):
            raise RuntimeError('PUBLIC_BASE_URL must use https when APP_ENV=production.')

    return Settings(
        app_env=app_env,
        testing=testing,
        secret_key=secret_key,
        cookie_secure=cookie_secure,
        session_max_age_seconds=session_max_age_seconds,
        database_url=database_url,
        timezone=(getenv('APP_TIMEZONE') or 'Europe/Moscow').strip() or 'Europe/Moscow',
        host=host,
        allowed_hosts=allowed_hosts,
        public_base_url=public_base_url,
        port=int(getenv('PORT', '8000')),
        reload=env_flag('RELOAD'),
        allow_local_private_data=env_flag('ALLOW_LOCAL_PRIVATE_DATA'),
        smtp_host='' if testing else (getenv('SMTP_HOST') or '').strip(),
        smtp_port=int(getenv('SMTP_PORT', '587')),
        smtp_username='' if testing else (getenv('SMTP_USERNAME') or '').strip(),
        smtp_password='' if testing else (getenv('SMTP_PASSWORD') or '').strip(),
        smtp_from_email='' if testing else (getenv('SMTP_FROM_EMAIL') or '').strip(),
        smtp_from_name=(getenv('SMTP_FROM_NAME') or 'Student Assistant').strip(),
        smtp_starttls=env_flag('SMTP_STARTTLS', 'true'),
        smtp_ssl=env_flag('SMTP_SSL'),
        password_reset_token_ttl_seconds=int(getenv('PASSWORD_RESET_TOKEN_TTL_SECONDS', '3600')),
        telegram_bot_token='' if disable_telegram else (
            (getenv('TELEGRAM_BOT_TOKEN') or '').strip()
            or (getenv('TELEGRAM_BOT_API_TOKEN') or '').strip()
        ),
        telegram_bot_api_base_url=(getenv('TELEGRAM_BOT_API_BASE_URL') or '').strip().rstrip('/'),
        telegram_link_code_ttl_minutes=telegram_link_code_ttl_minutes,
        telegram_use_webhook=env_flag('TELEGRAM_USE_WEBHOOK'),
        telegram_webhook_base_url=(
            getenv('TELEGRAM_WEBHOOK_BASE_URL') or ''
        ).strip().rstrip('/'),
        telegram_webhook_path=normalize_telegram_webhook_path(
            getenv('TELEGRAM_WEBHOOK_PATH', '/telegram/webhook')
        ),
        telegram_webhook_secret=(getenv('TELEGRAM_WEBHOOK_SECRET') or '').strip(),
        telegram_bot_host=(getenv('TELEGRAM_BOT_HOST') or '127.0.0.1').strip() or '127.0.0.1',
        telegram_bot_port=telegram_bot_port,
        telegram_bot_log_level=(
            getenv('TELEGRAM_BOT_LOG_LEVEL') or 'INFO'
        ).strip().upper() or 'INFO',
        telegram_bot_username=(
            getenv('TELEGRAM_BOT_USERNAME') or 'student_assistant_max_bot'
        ).strip().lstrip('@'),
        telegram_digest_check_interval_seconds=telegram_digest_check_interval_seconds,
        disable_telegram=disable_telegram,
        base_dir=base_dir,
    )


settings = get_settings()
