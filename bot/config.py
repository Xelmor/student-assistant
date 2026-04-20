from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def env_flag(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).strip().lower() == 'true'


@dataclass(frozen=True)
class BotSettings:
    bot_token: str
    api_base_url: str
    api_token: str
    webhook_base_url: str
    webhook_path: str
    webhook_secret: str
    use_webhook: bool
    host: str
    port: int
    log_level: str


def get_settings() -> BotSettings:
    return BotSettings(
        bot_token=(os.getenv('TELEGRAM_BOT_TOKEN') or '').strip(),
        api_base_url=(os.getenv('TELEGRAM_BOT_API_BASE_URL') or 'http://localhost:8000').rstrip('/'),
        api_token=(os.getenv('TELEGRAM_BOT_API_TOKEN') or '').strip(),
        webhook_base_url=(os.getenv('TELEGRAM_WEBHOOK_BASE_URL') or '').rstrip('/'),
        webhook_path=(os.getenv('TELEGRAM_WEBHOOK_PATH') or '/telegram/webhook').strip() or '/telegram/webhook',
        webhook_secret=(os.getenv('TELEGRAM_WEBHOOK_SECRET') or '').strip(),
        use_webhook=env_flag('TELEGRAM_USE_WEBHOOK'),
        host=os.getenv('TELEGRAM_BOT_HOST', '0.0.0.0'),
        port=int(os.getenv('TELEGRAM_BOT_PORT', '8081')),
        log_level=(os.getenv('TELEGRAM_BOT_LOG_LEVEL') or 'INFO').upper(),
    )


settings = get_settings()


def validate_settings() -> None:
    if not settings.bot_token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is required for the bot.')
    if not settings.api_token:
        raise RuntimeError('TELEGRAM_BOT_API_TOKEN is required for bot-to-site API access.')
