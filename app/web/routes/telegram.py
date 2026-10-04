import json
import logging
from hmac import compare_digest

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ...core.config import settings
from ...core.database import get_db
from ...services.telegram_bot import send_telegram_message
from ...services.telegram_delivery import process_update

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(settings.telegram_webhook_path)
@router.post(f'{settings.telegram_webhook_path}/{{webhook_secret}}')
async def telegram_webhook(request: Request, webhook_secret: str = '', db: Session = Depends(get_db)):
    configured = settings.telegram_webhook_secret
    header = request.headers.get('x-telegram-bot-api-secret-token', '')
    # Legacy URL remains valid; if a header is supplied it must also match.
    def matches(value):
        return compare_digest(value.encode('utf-8'), configured.encode('utf-8'))
    authorized = configured and (matches(header) if not webhook_secret else
                                matches(webhook_secret) and (not header or matches(header)))
    if not authorized:
        return JSONResponse({'ok': False}, status_code=403)
    if not settings.telegram_use_webhook or not settings.telegram_bot_token:
        return JSONResponse({'ok': False, 'error': 'transport_unavailable'}, status_code=503)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1_000_000:
            return JSONResponse({'ok': False}, status_code=413)
        body.extend(chunk)
    try:
        update = json.loads(body)
    except (ValueError, UnicodeError):
        return JSONResponse({'ok': False}, status_code=400)
    if not isinstance(update, dict) or type(update.get('update_id')) is not int or not 0 <= update['update_id'] < 2**63:
        return JSONResponse({'ok': False}, status_code=400)
    try:
        await run_in_threadpool(process_update, db, update, send_message=send_telegram_message)
    except Exception:
        db.rollback()
        logger.error('Telegram stage=webhook update_id=%s category=processing_failed', update['update_id'])
        return JSONResponse({'ok': False}, status_code=503)
    return JSONResponse({'ok': True})
