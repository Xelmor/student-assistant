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
    call_telegram_api,
    get_telegram_updates,
    send_telegram_message,
)


from app.services.telegram_delivery import process_update as process_durable_update, retry_pending_replies

logger = logging.getLogger(__name__)
POLLING_TIMEOUT_SECONDS = 25
RETRY_DELAY_SECONDS = 3


def process_update(
    update: dict,
    *,
    session_factory=SessionLocal,
    send_message: Callable[[TelegramReply], None] = send_telegram_message,
) -> None:
    db = session_factory()
    try:
        process_durable_update(db, update, send_message=send_message)
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
            logger.error('Telegram stage=process update_id=%s category=retry_pending', update_id)
            break
        if type(update_id) is int:
            candidate = update_id + 1
            if next_offset is None or candidate > next_offset:
                next_offset = candidate
    return next_offset


def run_polling(
    *,
    fetch_updates: Callable[..., list[dict]] = get_telegram_updates,
    processor: Callable[[dict], None] = process_update,
    sleep: Callable[[float], None] = time.sleep,
    retry_replies: Callable[[], None] | None = None,
) -> None:
    offset: int | None = None
    failures = 0
    processing_failures = 0
    while True:
        if retry_replies is not None:
            retry_replies()
        try:
            updates = fetch_updates(
                offset=offset,
                timeout=POLLING_TIMEOUT_SECONDS,
            )
        except TelegramAPIError as error:
            failures += 1
            if not error.retryable or failures >= 5:
                raise
            logger.warning(
                'Telegram getUpdates failed. Retrying in %s seconds.',
                RETRY_DELAY_SECONDS,
            )
            sleep(max(RETRY_DELAY_SECONDS, error.retry_after or 0))
            continue
        except Exception:
            failures += 1
            if failures >= 5:
                raise RuntimeError('Telegram polling failed after five attempts') from None
            logger.error(
                'Unexpected Telegram getUpdates failure. Retrying in %s seconds.',
                RETRY_DELAY_SECONDS,
            )
            sleep(RETRY_DELAY_SECONDS)
            continue

        failures = 0
        next_offset = process_updates(updates, offset, processor=processor)
        if updates and next_offset == offset:
            processing_failures += 1
            if processing_failures >= 5:
                raise RuntimeError('Telegram processing stalled; offset retained') from None
            sleep(RETRY_DELAY_SECONDS)
        else:
            processing_failures = 0
        offset = next_offset


def drain_pending_replies():
    with SessionLocal() as db:
        retry_pending_replies(db)


def configure_logging() -> None:
    log_level = getattr(logging, settings.telegram_bot_log_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )


def main() -> int:
    configure_logging()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if not settings.telegram_bot_token:
        print(
            'Telegram token is missing. Set TELEGRAM_BOT_TOKEN '
            'or TELEGRAM_BOT_API_TOKEN.',
            file=sys.stderr,
        )
        return 1
    if settings.app_env == 'production':
        print('Polling is local-development only; production requires webhook.', file=sys.stderr)
        return 1
    if settings.telegram_use_webhook:
        print(
            'Polling requires TELEGRAM_USE_WEBHOOK=false. '
            'Disable webhook mode for local testing.',
            file=sys.stderr,
        )
        return 1

    try:
        if call_telegram_api('getWebhookInfo', {}).get('result', {}).get('url'):
            print('Webhook is installed. Explicitly switch transport before polling.', file=sys.stderr)
            return 1
    except TelegramAPIError as error:
        logger.error('Telegram startup category=%s', error.category)
        return 1
    run_migrations()

    print('Telegram polling started. Press Ctrl+C to stop.', flush=True)
    try:
        run_polling(retry_replies=drain_pending_replies)
    except TelegramAPIError as error:
        logger.error('Telegram polling stopped category=%s', error.category)
        return 1
    except Exception:
        logger.error('Telegram polling stopped category=processing_failed')
        return 1
    except KeyboardInterrupt:
        print('\nTelegram polling stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
