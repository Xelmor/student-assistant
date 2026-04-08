import os
import sys
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.models import User, Task, ScheduleItem, TelegramBinding, TelegramLinkCode
from app.utils import WEEKDAYS

BOT_TOKEN = os.getenv('BOT_TOKEN', '')

if not BOT_TOKEN:
    raise RuntimeError('Укажи BOT_TOKEN в переменных окружения.')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def get_db() -> Session:
    return SessionLocal()


def get_user_by_telegram_username(db: Session, tg_username: str):
    if not tg_username:
        return None
    return db.query(User).filter(User.username == tg_username).first()


def get_user_by_telegram_id(db: Session, telegram_user_id: int):
    binding = db.query(TelegramBinding).filter(
        TelegramBinding.telegram_user_id == str(telegram_user_id)
    ).first()
    if not binding:
        return None
    return db.query(User).filter(User.id == binding.user_id).first()


@dp.message(Command('start'))
async def cmd_start(message: Message):
    text = (
        'Привет! Я бот Student Assistant.\n\n'
        'Чтобы я связал Telegram с твоим аккаунтом на сайте, сделай так:\n'
        '1) В веб-версии открой раздел Telegram\n'
        '2) Сгенерируй код\n'
        '3) Отправь сюда: /link КОД\n\n'
        'Команды:\n'
        '/link <код> — привязать аккаунт\n'
        '/today — задачи и пары на сегодня\n'
        '/tasks — активные задачи\n'
        '/help — помощь'
    )
    await message.answer(text)


@dp.message(Command('help'))
async def cmd_help(message: Message):
    await message.answer('Команды: /link <код>, /today, /tasks')


@dp.message(Command('link'))
async def cmd_link(message: Message, command: CommandObject):
    db = get_db()
    try:
        code_value = (command.args or '').strip().upper()
        if not code_value:
            await message.answer('Отправь команду в формате: /link КОД')
            return

        now = datetime.utcnow()
        link_code = db.query(TelegramLinkCode).filter(
            TelegramLinkCode.code == code_value,
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > now,
        ).first()
        if not link_code:
            await message.answer('Код не найден или просрочен. Сгенерируй новый код в веб-версии.')
            return

        existing_for_tg = db.query(TelegramBinding).filter(
            TelegramBinding.telegram_user_id == str(message.from_user.id)
        ).first()
        if existing_for_tg and existing_for_tg.user_id != link_code.user_id:
            await message.answer('Этот Telegram уже привязан к другому аккаунту.')
            return

        db.query(TelegramBinding).filter(
            TelegramBinding.user_id == link_code.user_id
        ).delete(synchronize_session=False)

        binding = TelegramBinding(
            user_id=link_code.user_id,
            telegram_user_id=str(message.from_user.id),
            telegram_username=message.from_user.username,
        )
        db.add(binding)
        link_code.used_at = now
        db.commit()

        await message.answer('Готово! Telegram успешно привязан.')
    finally:
        db.close()


@dp.message(Command('tasks'))
async def cmd_tasks(message: Message):
    db = get_db()
    try:
        user = get_user_by_telegram_id(db, message.from_user.id)
        if not user:
            user = get_user_by_telegram_username(db, message.from_user.username)
        if not user:
            await message.answer('Аккаунт не привязан. На сайте открой Telegram и выполни /link КОД.')
            return

        tasks = db.query(Task).filter(Task.user_id == user.id, Task.is_completed == False).order_by(Task.deadline.asc()).limit(10).all()
        if not tasks:
            await message.answer('Активных задач нет.')
            return

        lines = ['Твои активные задачи:']
        for task in tasks:
            deadline_text = task.deadline.strftime('%d.%m %H:%M') if task.deadline else 'без дедлайна'
            subject_text = f'[{task.subject.name}] ' if task.subject else ''
            lines.append(f'• {subject_text}{task.title} — {deadline_text}')
        await message.answer('\n'.join(lines))
    finally:
        db.close()


@dp.message(Command('today'))
async def cmd_today(message: Message):
    db = get_db()
    try:
        user = get_user_by_telegram_id(db, message.from_user.id)
        if not user:
            user = get_user_by_telegram_username(db, message.from_user.username)
        if not user:
            await message.answer('Аккаунт не привязан. На сайте открой Telegram и выполни /link КОД.')
            return

        now = datetime.now()
        weekday = now.weekday()

        tasks = db.query(Task).filter(Task.user_id == user.id, Task.is_completed == False).all()
        today_tasks = [t for t in tasks if t.deadline and t.deadline.date() == now.date()]
        today_schedule = db.query(ScheduleItem).filter(
            ScheduleItem.user_id == user.id,
            ScheduleItem.weekday == weekday,
        ).order_by(ScheduleItem.start_time.asc()).all()

        lines = [f'План на сегодня: {WEEKDAYS[weekday]}']
        lines.append('\nПары:')
        if today_schedule:
            for item in today_schedule:
                lines.append(f'• {item.start_time.strftime("%H:%M")}-{item.end_time.strftime("%H:%M")} {item.subject.name}')
        else:
            lines.append('• Пар нет')

        lines.append('\nДедлайны сегодня:')
        if today_tasks:
            for task in today_tasks:
                lines.append(f'• {task.title} до {task.deadline.strftime("%H:%M")}')
        else:
            lines.append('• На сегодня дедлайнов нет')

        await message.answer('\n'.join(lines))
    finally:
        db.close()


async def main():
    await dp.start_polling(bot)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
