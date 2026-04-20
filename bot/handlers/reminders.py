from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..api_client import NotLinkedError, StudentAssistantApiClient
from ..keyboards.common import main_menu_keyboard, reminders_keyboard
from ..services.formatters import format_reminders


router = Router()


@router.message(F.text == 'Напоминания')
async def reminders_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        settings = await api_client.get_reminders(message.chat.id)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return

    await message.answer(
        format_reminders(settings),
        reply_markup=main_menu_keyboard(),
    )
    await message.answer('Изменить настройки:', reply_markup=reminders_keyboard(settings))


@router.callback_query(F.data.startswith('reminders:'))
async def reminders_callback(callback: CallbackQuery, api_client: StudentAssistantApiClient) -> None:
    try:
        settings = await api_client.get_reminders(callback.message.chat.id)
    except NotLinkedError:
        await callback.answer('Сначала привяжи аккаунт через /login', show_alert=True)
        return
    action = callback.data.split(':', 1)[1]

    if action == 'toggle_all':
        settings = await api_client.update_reminders(
            callback.message.chat.id,
            {'notifications_enabled': not settings['notifications_enabled']},
        )
    elif action == 'toggle_deadlines':
        settings = await api_client.update_reminders(
            callback.message.chat.id,
            {'deadline_reminders_enabled': not settings['deadline_reminders_enabled']},
        )
    elif action == 'toggle_schedule':
        settings = await api_client.update_reminders(
            callback.message.chat.id,
            {'schedule_reminders_enabled': not settings['schedule_reminders_enabled']},
        )

    await callback.message.edit_text(
        format_reminders(settings),
        reply_markup=reminders_keyboard(settings),
    )
    await callback.answer('Настройки обновлены')
