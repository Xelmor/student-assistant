from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from .api_client import StudentAssistantApiClient
from .config import settings, validate_settings
from .main import build_dispatcher, configure_logging


validate_settings()
api_client = StudentAssistantApiClient()
bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dispatcher = build_dispatcher(api_client)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    if settings.webhook_base_url:
        await bot.set_webhook(
            url=f'{settings.webhook_base_url}{settings.webhook_path}',
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
    yield
    await api_client.close()
    await bot.session.close()


app = FastAPI(title='Student Assistant Telegram Webhook', lifespan=lifespan)


@app.post(settings.webhook_path)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if settings.webhook_secret and x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail='Invalid webhook secret.')

    update = Update.model_validate(await request.json(), context={'bot': bot})
    await dispatcher.feed_update(bot, update)
    return {'ok': True}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)
