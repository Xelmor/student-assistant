from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..api_client import ApiClientError, NotLinkedError, StudentAssistantApiClient
from ..keyboards.common import main_menu_keyboard


router = Router()


class TaskCreationStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_deadline = State()


@router.message(F.text == 'Добавить задачу')
async def add_task_start(message: Message, state: FSMContext) -> None:
    await state.set_state(TaskCreationStates.waiting_for_title)
    await message.answer(
        'Отправь название задачи. После этого я попрошу дедлайн в формате ГГГГ-ММ-ДД ЧЧ:ММ или символ "-" без дедлайна.'
    )


@router.message(TaskCreationStates.waiting_for_title)
async def add_task_title(message: Message, state: FSMContext) -> None:
    title = (message.text or '').strip()
    if not title:
        await message.answer('Название не должно быть пустым.')
        return
    await state.update_data(title=title)
    await state.set_state(TaskCreationStates.waiting_for_deadline)
    await message.answer('Теперь отправь дедлайн в формате 2026-04-30 18:00 или "-" без дедлайна.')


@router.message(TaskCreationStates.waiting_for_deadline)
async def add_task_deadline(
    message: Message,
    state: FSMContext,
    api_client: StudentAssistantApiClient,
) -> None:
    raw_value = (message.text or '').strip()
    payload = await state.get_data()
    body = {'title': payload['title']}

    if raw_value != '-':
        normalized_value = raw_value.replace(' ', 'T')
        body['deadline'] = normalized_value

    try:
        await api_client.create_task(message.chat.id, body)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        await state.clear()
        return
    except ApiClientError:
        await message.answer('Не удалось создать задачу. Проверь формат дедлайна и попробуй снова.')
        return

    await state.clear()
    await message.answer('Задача добавлена.', reply_markup=main_menu_keyboard())
