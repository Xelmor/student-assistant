from __future__ import annotations

from dataclasses import dataclass
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
    base_dir: Path


def get_settings() -> Settings:
    from os import getenv

    base_dir = Path(__file__).resolve().parent.parent
    app_env = (getenv('APP_ENV') or 'development').strip().lower()
    secret_key = (getenv('SECRET_KEY') or '').strip()
    cookie_secure = env_flag('COOKIE_SECURE')
    session_max_age_seconds = int(getenv('SESSION_MAX_AGE_SECONDS', '43200'))

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
        smtp_host=(getenv('SMTP_HOST') or '').strip(),
        smtp_port=int(getenv('SMTP_PORT', '587')),
        smtp_username=(getenv('SMTP_USERNAME') or '').strip(),
        smtp_password=(getenv('SMTP_PASSWORD') or '').strip(),
        smtp_from_email=(getenv('SMTP_FROM_EMAIL') or '').strip(),
        smtp_from_name=(getenv('SMTP_FROM_NAME') or 'Student Assistant').strip(),
        smtp_starttls=env_flag('SMTP_STARTTLS', 'true'),
        smtp_ssl=env_flag('SMTP_SSL'),
        password_reset_token_ttl_seconds=int(getenv('PASSWORD_RESET_TOKEN_TTL_SECONDS', '3600')),
        base_dir=base_dir,
    )


settings = get_settings()
