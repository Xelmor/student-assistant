from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..api_client import NotLinkedError, StudentAssistantApiClient
from ..keyboards.common import main_menu_keyboard
from ..services.formatters import format_notes, format_schedule, format_subjects, format_tasks


router = Router()


def _help_text() -> str:
    return (
        'Команды бота:\n'
        '/start - главное меню\n'
        '/help - список команд\n'
        '/login - привязать Telegram к аккаунту сайта\n\n'
        'Через меню можно открыть расписание, задачи, дедлайны, предметы, заметки и настройки напоминаний.'
    )


@router.message(Command('start'))
async def start_handler(message: Message) -> None:
    await message.answer(
        'Привет! Я бот Student Assistant. Через меня можно быстро посмотреть расписание, задачи и дедлайны.',
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command('help'))
async def help_handler(message: Message) -> None:
    await message.answer(_help_text(), reply_markup=main_menu_keyboard())


@router.message(F.text == 'Предметы')
async def subjects_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        subjects = await api_client.get_subjects(message.chat.id)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return
    await message.answer(format_subjects(subjects), reply_markup=main_menu_keyboard())


@router.message(F.text == 'Заметки')
async def notes_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        notes = await api_client.get_notes(message.chat.id, limit=5)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return
    await message.answer(format_notes(notes), reply_markup=main_menu_keyboard())


@router.message(F.text == 'Мои задачи')
async def tasks_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        tasks = await api_client.get_tasks(message.chat.id, status='active', limit=10)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return
    await message.answer(format_tasks(tasks, 'Активные задачи:'), reply_markup=main_menu_keyboard())


@router.message(F.text == 'Ближайшие дедлайны')
async def deadlines_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        tasks = await api_client.get_deadlines(message.chat.id, limit=10)
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return
    await message.answer(format_tasks(tasks, 'Ближайшие дедлайны:'), reply_markup=main_menu_keyboard())


@router.message(F.text == 'Моё расписание')
async def schedule_handler(message: Message, api_client: StudentAssistantApiClient) -> None:
    try:
        today = await api_client.get_schedule(message.chat.id, scope='today')
        week = await api_client.get_schedule(message.chat.id, scope='week')
    except NotLinkedError:
        await message.answer('Сначала привяжи аккаунт командой /login.')
        return

    text = (
        'Сегодня:\n'
        f'{format_schedule(today, empty_text="Сегодня занятий нет.")}\n\n'
        'На неделю:\n'
        f'{format_schedule(week, empty_text="Расписание пока пустое.")}'
    )
    await message.answer(text, reply_markup=main_menu_keyboard())
