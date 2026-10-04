"""Publish the six public menu commands; hidden commands keep their handlers."""
from __future__ import annotations

import sys

from app.core.config import settings
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, install_telegram_commands


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

    print(f'Telegram menu updated: {len(BOT_COMMANDS)} commands. Hidden commands remain available.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
