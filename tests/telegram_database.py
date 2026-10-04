"""Opt-in isolated PostgreSQL backend for the existing Telegram test harness."""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.core.migrations import run_migrations

_migrated = set()


def postgres_test_engine():
    target = os.getenv('TELEGRAM_TEST_DATABASE_URL')
    if not target:
        return None
    url = make_url(target)
    if url.get_backend_name() != 'postgresql' or not (url.database or '').startswith('sa_telegram_test_'):
        raise RuntimeError('Telegram tests require an explicitly isolated sa_telegram_test_* PostgreSQL database')
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
                           connect_args={'options': '-c lock_timeout=10000 -c statement_timeout=30000'})
    if target not in _migrated:
        run_migrations(engine)
        _migrated.add(target)
    # Never run against DATABASE_URL implicitly. Only the opt-in test DB is reset.
    from app.core.database import Base
    names = ', '.join('"' + name + '"' for name in Base.metadata.tables)
    with engine.begin() as connection:
        connection.execute(text(f'TRUNCATE {names} RESTART IDENTITY CASCADE'))
    return engine
