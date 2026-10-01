"""Read-only Telegram diagnostics. Never prints credentials, update contents or URLs."""
import argparse
import json
from hashlib import sha256
from urllib.parse import quote

from sqlalchemy import inspect, text
from app.core.config import settings
from app.core.database import engine, SessionLocal
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
        required = {'users', 'workspaces', 'tasks', 'schedule_items', 'telegram_updates', 'telegram_state', 'telegram_deadline_reminder_logs'}
        result['database_accessible'] = True
        result['missing_tables'] = sorted(required - tables)
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
                # Whitelist categories; Telegram's raw error may contain a secret URL.
                error = str(hook.get('last_error_message', '')).lower()
                result['webhook_delivery_error'] = ('none' if not error else 'timeout' if 'timeout' in error or 'timed out' in error else 'tls' if 'ssl' in error or 'certificate' in error else 'http_rejected' if 'response' in error else 'delivery_failed')
                result['network'] = 'checked'
            except TelegramAPIError as error:
                result['network'] = error.category
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', action='store_true', help='Explicitly call getMe and getWebhookInfo only')
    args = parser.parse_args()
    print(json.dumps(report(network=args.network), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
