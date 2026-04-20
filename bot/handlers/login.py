from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..api_client import ApiClientError, StudentAssistantApiClient
from ..keyboards.common import main_menu_keyboard


router = Router()


class LoginStates(StatesGroup):
    waiting_for_code = State()


@router.message(Command('login'))
async def login_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(LoginStates.waiting_for_code)
    await message.answer(
        'Открой сайт, зайди в профиль и возьми одноразовый код привязки Telegram. Затем отправь сюда 6 цифр.',
        reply_markup=main_menu_keyboard(),
    )


@router.message(LoginStates.waiting_for_code)
async def receive_code(
    message: Message,
    state: FSMContext,
    api_client: StudentAssistantApiClient,
) -> None:
    code = (message.text or '').strip()
    if not (code.isdigit() and len(code) == 6):
        await message.answer('Нужен код из 6 цифр. Попробуй ещё раз или снова используй /login.')
        return

    try:
        response = await api_client.link_telegram(code, message.chat.id, message.from_user.username)
    except ApiClientError:
        await message.answer('Не удалось привязать аккаунт. Проверь код и попробуй снова.')
        return

    await state.clear()
    await message.answer(
        f"Аккаунт привязан. Привет, {response['username']}!",
        reply_markup=main_menu_keyboard(),
    )
