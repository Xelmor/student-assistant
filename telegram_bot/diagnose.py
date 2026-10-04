"""Read-only Telegram diagnostics. Never prints credentials, update contents or URLs."""
import argparse
import json
from hashlib import sha256
from urllib.parse import quote, urlparse

from sqlalchemy import inspect, text
from app.core.config import settings, DEVELOPMENT_SECRET_KEY
from app.core.database import Base, engine, SessionLocal
from app.models import TelegramState, TelegramUpdate
from app.services.telegram_bot import call_telegram_api, TelegramAPIError
from app.services.telegram_state import utcnow
from telegram_bot.set_webhook import build_webhook_url


def report(*, network=False):
    result = {
        'token_configured': bool(settings.telegram_bot_token),
        'username_configured': bool(settings.telegram_bot_username),
        'webhook_secret_configured': bool(settings.telegram_webhook_secret),
        'public_origin_configured': bool(settings.public_base_url),
        'public_origin': (urlparse(settings.public_base_url).scheme + '://' + (urlparse(settings.public_base_url).hostname or '')) if settings.public_base_url else None,
        'pending_updates': None, 'pending_replies': None, 'failed_replies': None,
        'missing_tables': [],
        'testing': settings.testing, 'disabled': settings.disable_telegram,
        'mode': 'webhook' if settings.telegram_use_webhook else 'polling',
        'legacy_base_url_configured': bool(settings.telegram_bot_api_base_url),
        'database_kind': engine.dialect.name,
        'database_target_fingerprint': sha256(engine.url.render_as_string(hide_password=True).encode()).hexdigest()[:12],
        'database_shared_across_services': 'must_verify_in_hosting' if engine.dialect.name != 'sqlite' else False,
        'receiver_process': 'not_measured', 'network': 'not_requested',
    }
    try:
        from pathlib import Path
        if engine.dialect.name == 'sqlite' and engine.url.database != ':memory:' and not Path(engine.url.database).exists():
            raise RuntimeError('Database does not exist')
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
            tables = set(inspect(connection).get_table_names())
        required = set(Base.metadata.tables) | {'schema_migrations'}
        result['database_accessible'] = True
        result['tables'] = sorted(tables)
        result['missing_tables'] = sorted(required - tables)
        if 'schema_migrations' in tables:
            from app.core.migrations import MIGRATIONS
            with engine.connect() as connection:
                applied = set(connection.execute(text('SELECT version FROM schema_migrations')).scalars())
            result['missing_migrations'] = sorted(m.version for m in MIGRATIONS if m.version not in applied)
        else:
            result['missing_migrations'] = ['migration_registry_missing']
        with SessionLocal() as db:
            if 'telegram_state' in tables:
                row = db.get(TelegramState, 'scheduler-heartbeat')
                result['scheduler'] = ('recent_' + row.data.get('state', 'unknown') if row.expires_at > utcnow() else 'stale') if row else 'not_observed'
            if 'telegram_updates' in tables:
                result['pending_replies'] = db.query(TelegramUpdate).filter_by(status='pending').count()
                result['failed_replies'] = db.query(TelegramUpdate).filter_by(status='failed').count()
    except Exception:
        result['database_accessible'] = False
    try:
        expected = build_webhook_url()
        result['webhook_configuration_valid'] = True
    except ValueError:
        expected = None
        result['webhook_configuration_valid'] = False
    if network:
        if not settings.telegram_bot_token:
            result['network'] = 'token_missing_or_disabled'
        else:
            try:
                me = call_telegram_api('getMe', {}).get('result', {})
                result['username_matches'] = str(me.get('username', '')).lower() == settings.telegram_bot_username.lower()
                hook = call_telegram_api('getWebhookInfo', {}).get('result', {})
                actual = hook.get('url', '')
                result['webhook_present'] = bool(actual)
                result['webhook_matches'] = bool(expected and actual == expected)
                result['webhook_legacy_matches'] = bool(expected and actual == expected + '/' + quote(settings.telegram_webhook_secret, safe=''))
                result['pending_update_count'] = hook.get('pending_update_count', 0)
                result['pending_updates'] = result['pending_update_count']
                # Whitelist categories; Telegram's raw error may contain a secret URL.
                error = str(hook.get('last_error_message', '')).lower()
                result['webhook_delivery_error'] = ('none' if not error else 'timeout' if 'timeout' in error or 'timed out' in error else 'tls' if 'ssl' in error or 'certificate' in error else 'http_rejected' if 'response' in error else 'delivery_failed')
                result['network'] = 'checked'
            except TelegramAPIError as error:
                result['network'] = error.category
    blockers = []
    for valid, name in [
        (bool(settings.telegram_bot_token), 'token_missing_or_disabled'),
        (bool(settings.telegram_bot_username), 'username_missing'),
        (settings.telegram_use_webhook, 'production_requires_webhook'),
        (engine.dialect.name == 'postgresql', 'production_requires_shared_postgresql'),
        (result.get('database_accessible'), 'database_inaccessible'),
        (not result['missing_tables'] and not result.get('missing_migrations'), 'migrations_incomplete'),
        (result.get('webhook_configuration_valid'), 'invalid_webhook_configuration'),
        (len(settings.telegram_webhook_secret) >= 32, 'weak_webhook_secret'),
        (settings.secret_key != DEVELOPMENT_SECRET_KEY, 'temporary_secret_key'),
        (result.get('scheduler', '').startswith('recent_') and result.get('scheduler') != 'recent_degraded', 'scheduler_not_healthy'),
        (result.get('network') == 'checked', 'network_not_verified'),
        (result.get('username_matches'), 'username_not_verified'),
        (result.get('webhook_matches'), 'webhook_not_verified'),
        (not result.get('failed_replies'), 'failed_replies_present'),
    ]:
        if not valid:
            blockers.append(name)
    result['configuration_valid'] = bool(settings.telegram_bot_token and settings.telegram_bot_username
        and (not settings.telegram_use_webhook or result.get('webhook_configuration_valid')))
    result['production_readiness_blockers'] = blockers
    result['production_safe'] = not blockers
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', action='store_true', help='Explicitly call getMe and getWebhookInfo only')
    args = parser.parse_args()
    result = report(network=args.network)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["configuration_valid"] and result.get("database_accessible") and not result["missing_tables"] else 1


if __name__ == '__main__':
    raise SystemExit(main())
