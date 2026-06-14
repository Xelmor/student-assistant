from __future__ import annotations

import sys

from app.core.config import settings
from app.services.telegram_bot import TelegramAPIError, install_telegram_commands


def main() -> int:
    if not settings.telegram_bot_token:
        print(
            'Telegram token is missing. Set TELEGRAM_BOT_TOKEN '
            'or TELEGRAM_BOT_API_TOKEN.',
            file=sys.stderr,
        )
        return 1

    try:
        install_telegram_commands()
    except TelegramAPIError as error:
        print(f'Telegram commands were not updated: {error}', file=sys.stderr)
        return 1

    print('Telegram bot commands updated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
