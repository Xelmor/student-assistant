"""Redact legacy secret endpoints in application/access/client logs."""
import logging
import re

from .config import settings


class TelegramLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for secret in (settings.telegram_bot_token, settings.telegram_webhook_secret):
            if secret:
                message = message.replace(secret, '[redacted]')
        message = re.sub(re.escape(settings.telegram_webhook_path) + r'/[^\s?"\']+', settings.telegram_webhook_path + '/[redacted]', message)
        message = re.sub(r'/bot[^/\s]+/', '/bot[redacted]/', message)
        record.msg, record.args = message, ()
        if settings.telegram_webhook_path in message:
            record.exc_info = None
            record.exc_text = None
        return True


def install_telegram_log_filter():
    for name in ('uvicorn.access', 'uvicorn.error', 'httpx', 'app.main'):
        logger = logging.getLogger(name)
        if not any(isinstance(item, TelegramLogFilter) for item in logger.filters):
            logger.addFilter(TelegramLogFilter())
