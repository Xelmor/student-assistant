from __future__ import annotations

import sys
from urllib.parse import quote, urlparse

from app.core.config import settings
from app.services.telegram_bot import TelegramAPIError, install_telegram_webhook


def build_webhook_url() -> str:
    public_base_url = (
        settings.telegram_webhook_base_url
        or settings.telegram_bot_api_base_url
    ).rstrip('/')
    if not public_base_url:
        raise ValueError(
            'Set TELEGRAM_WEBHOOK_BASE_URL or TELEGRAM_BOT_API_BASE_URL.'
        )
    parsed = urlparse(public_base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Telegram webhook base URL must be an absolute http(s) URL.')
    if not settings.telegram_webhook_secret:
        raise ValueError('Set TELEGRAM_WEBHOOK_SECRET.')

    encoded_secret = quote(settings.telegram_webhook_secret, safe='')
    return f'{public_base_url}{settings.telegram_webhook_path}/{encoded_secret}'


def main() -> int:
    if not settings.telegram_bot_token:
        print(
            'Telegram token is missing. Set TELEGRAM_BOT_TOKEN '
            'or TELEGRAM_BOT_API_TOKEN.',
            file=sys.stderr,
        )
        return 1

    try:
        webhook_url = build_webhook_url()
        install_telegram_webhook(webhook_url)
    except (ValueError, TelegramAPIError) as error:
        print(f'Webhook was not installed: {error}', file=sys.stderr)
        return 1

    print(
        'Telegram webhook installed: '
        f'{settings.telegram_webhook_path}/<secret>'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
