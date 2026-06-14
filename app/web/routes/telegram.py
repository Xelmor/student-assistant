import logging
from hmac import compare_digest

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ...core.config import settings
from ...core.database import get_db
from ...services.telegram_bot import (
    TelegramAPIError,
    handle_telegram_update,
    send_telegram_message,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(f'{settings.telegram_webhook_path}/{{webhook_secret}}')
async def telegram_webhook(
    webhook_secret: str,
    request: Request,
    db: Session = Depends(get_db),
):
    configured_secret = settings.telegram_webhook_secret
    if not configured_secret or not compare_digest(webhook_secret, configured_secret):
        return JSONResponse({'ok': False}, status_code=403)

    content_length = request.headers.get('content-length')
    if content_length and content_length.isdigit() and int(content_length) > 1_000_000:
        return JSONResponse({'ok': False}, status_code=413)

    try:
        update = await request.json()
    except ValueError:
        return JSONResponse({'ok': True})
    if not isinstance(update, dict):
        return JSONResponse({'ok': True})

    try:
        reply = handle_telegram_update(db, update)
        if reply is not None:
            if settings.telegram_bot_token:
                await run_in_threadpool(send_telegram_message, reply)
            else:
                logger.warning('Telegram update handled, but the bot token is not configured.')
    except TelegramAPIError:
        logger.warning('Telegram API request failed while processing an update.')
    except Exception:
        db.rollback()
        logger.exception('Telegram update processing failed.')

    return JSONResponse({'ok': True})
