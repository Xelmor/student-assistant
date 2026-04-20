from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .api_client import StudentAssistantApiClient
from .config import settings, validate_settings
from .handlers import register_handlers


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )


def build_dispatcher(api_client: StudentAssistantApiClient) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)

    @dp.error()
    async def error_handler(event):
        logging.getLogger(__name__).exception('Bot update failed: %s', event.exception)
        if getattr(event, 'update', None) and getattr(event.update, 'message', None):
            await event.update.message.answer('Произошла ошибка. Попробуй ещё раз позже.')
        return True

    dp['api_client'] = api_client
    return dp


async def main() -> None:
    validate_settings()
    configure_logging()
    api_client = StudentAssistantApiClient()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(api_client)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await api_client.close()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
