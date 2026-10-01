from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import urlparse

from app.core.config import settings
from app.services.telegram_bot import TelegramAPIError, install_telegram_webhook, delete_telegram_webhook


def build_webhook_url() -> str:
    origin = (settings.telegram_webhook_base_url or settings.public_base_url or settings.telegram_bot_api_base_url).rstrip('/')
    parsed = urlparse(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise ValueError('Set a public HTTPS origin in TELEGRAM_WEBHOOK_BASE_URL or PUBLIC_BASE_URL (no path or credentials).')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', settings.telegram_webhook_secret):
        raise ValueError('TELEGRAM_WEBHOOK_SECRET must contain 1–256 URL-safe characters.')
    return f'{origin}{settings.telegram_webhook_path}'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Explicit Telegram transport setup; never drops pending updates.')
    parser.add_argument('--delete-for-polling', action='store_true')
    args = parser.parse_args(argv)
    if not settings.telegram_bot_token:
        print('Telegram token is missing or disabled.', file=sys.stderr)
        return 1
    try:
        if args.delete_for_polling:
            if settings.telegram_use_webhook:
                raise ValueError('Set TELEGRAM_USE_WEBHOOK=false before switching to polling.')
            delete_telegram_webhook()
        else:
            if not settings.telegram_use_webhook:
                raise ValueError('Set TELEGRAM_USE_WEBHOOK=true before installing webhook.')
            install_telegram_webhook(build_webhook_url())
    except (ValueError, TelegramAPIError) as error:
        print(f'Transport was not changed: {error}', file=sys.stderr)
        return 1
    print('Telegram transport updated; pending updates retained.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
