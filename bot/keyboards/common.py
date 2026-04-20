from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Моё расписание'), KeyboardButton(text='Мои задачи')],
            [KeyboardButton(text='Ближайшие дедлайны'), KeyboardButton(text='Предметы')],
            [KeyboardButton(text='Заметки'), KeyboardButton(text='Добавить задачу')],
            [KeyboardButton(text='Напоминания')],
        ],
        resize_keyboard=True,
    )


def reminders_keyboard(settings: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=('Отключить все' if settings['notifications_enabled'] else 'Включить все'),
        callback_data='reminders:toggle_all',
    )
    builder.button(
        text=('Дедлайны: вкл' if settings['deadline_reminders_enabled'] else 'Дедлайны: выкл'),
        callback_data='reminders:toggle_deadlines',
    )
    builder.button(
        text=('Пары: вкл' if settings['schedule_reminders_enabled'] else 'Пары: выкл'),
        callback_data='reminders:toggle_schedule',
    )
    builder.adjust(1)
    return builder.as_markup()
