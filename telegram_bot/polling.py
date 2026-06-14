from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Iterable

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.migrations import run_migrations
from app.services.telegram_bot import (
    TelegramAPIError,
    TelegramReply,
    delete_telegram_webhook,
    get_telegram_updates,
    handle_telegram_update,
    send_telegram_message,
)


logger = logging.getLogger(__name__)
SAFE_ERROR_MESSAGE = 'Произошла ошибка. Попробуй ещё раз позже.'
POLLING_TIMEOUT_SECONDS = 25
RETRY_DELAY_SECONDS = 3


def get_update_chat_id(update: dict) -> int | None:
    callback = update.get('callback_query')
    message = callback.get('message') if isinstance(callback, dict) else update.get('message')
    if not isinstance(message, dict):
        return None
    chat = message.get('chat')
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get('id')
    return chat_id if isinstance(chat_id, int) else None


def process_update(
    update: dict,
    *,
    session_factory=SessionLocal,
    send_message: Callable[[TelegramReply], None] = send_telegram_message,
) -> None:
    db = session_factory()
    try:
        try:
            reply = handle_telegram_update(db, update)
        except Exception:
            db.rollback()
            logger.exception('Telegram polling update processing failed.')
            chat_id = get_update_chat_id(update)
            reply = (
                TelegramReply(chat_id=chat_id, text=SAFE_ERROR_MESSAGE)
                if chat_id is not None
                else None
            )

        if reply is None:
            return
        try:
            send_message(reply)
        except TelegramAPIError:
            logger.warning('Could not send a Telegram polling response.')
    except Exception:
        logger.exception('Unexpected Telegram polling response failure.')
    finally:
        db.close()


def process_updates(
    updates: Iterable[dict],
    offset: int | None,
    *,
    processor: Callable[[dict], None] = process_update,
) -> int | None:
    next_offset = offset
    for update in updates:
        update_id = update.get('update_id')
        try:
            processor(update)
        except Exception:
            logger.exception('Unexpected Telegram polling processor failure.')
        finally:
            if isinstance(update_id, int):
                candidate = update_id + 1
                if next_offset is None or candidate > next_offset:
                    next_offset = candidate
    return next_offset


def run_polling(
    *,
    fetch_updates: Callable[..., list[dict]] = get_telegram_updates,
    processor: Callable[[dict], None] = process_update,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    offset: int | None = None
    while True:
        try:
            updates = fetch_updates(
                offset=offset,
                timeout=POLLING_TIMEOUT_SECONDS,
            )
        except TelegramAPIError:
            logger.warning(
                'Telegram getUpdates failed. Retrying in %s seconds.',
                RETRY_DELAY_SECONDS,
            )
            sleep(RETRY_DELAY_SECONDS)
            continue
        except Exception:
            logger.exception(
                'Unexpected Telegram getUpdates failure. Retrying in %s seconds.',
                RETRY_DELAY_SECONDS,
            )
            sleep(RETRY_DELAY_SECONDS)
            continue

        offset = process_updates(updates, offset, processor=processor)


def configure_logging() -> None:
    log_level = getattr(logging, settings.telegram_bot_log_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )


def main() -> int:
    configure_logging()
    if not settings.telegram_bot_token:
        print(
            'Telegram token is missing. Set TELEGRAM_BOT_TOKEN '
            'or TELEGRAM_BOT_API_TOKEN.',
            file=sys.stderr,
        )
        return 1
    if settings.telegram_use_webhook:
        print(
            'Polling requires TELEGRAM_USE_WEBHOOK=false. '
            'Disable webhook mode for local testing.',
            file=sys.stderr,
        )
        return 1

    run_migrations()
    try:
        delete_telegram_webhook()
    except TelegramAPIError:
        logger.warning(
            'Could not delete the Telegram webhook. Polling will still be attempted.'
        )

    print('Telegram polling started. Press Ctrl+C to stop.', flush=True)
    try:
        run_polling()
    except KeyboardInterrupt:
        print('\nTelegram polling stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
