from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.migrations import run_migrations
from app.models import Task, TelegramDeadlineReminderLog, User
from app.services.telegram_bot import (
    TelegramAPIError,
    TelegramReply,
    send_telegram_message,
)
from app.services.telegram_digest import (
    build_morning_digest_message,
    digest_local_datetime,
    digest_send_time,
)
from app.services.telegram_notifications import (
    build_deadline_reminder_message,
    deadline_reminder_date_key,
    deadline_reminder_hours,
)


logger = logging.getLogger(__name__)


def is_digest_due(user: User, now_utc: datetime | None = None) -> bool:
    if (
        not user.telegram_morning_digest_enabled
        or user.telegram_user_id is None
        or user.telegram_chat_id is None
    ):
        return False

    local_now = digest_local_datetime(user, now_utc)
    if user.telegram_morning_digest_last_sent_date == local_now.date():
        return False
    return local_now.time().replace(tzinfo=None) >= digest_send_time(user)


def process_due_digests(
    db: Session,
    *,
    now_utc: datetime | None = None,
    send_message: Callable[[TelegramReply], None] = send_telegram_message,
) -> int:
    current_utc = now_utc or datetime.now(UTC)
    users = (
        db.query(User)
        .filter(
            User.telegram_morning_digest_enabled.is_(True),
            User.telegram_user_id.is_not(None),
            User.telegram_chat_id.is_not(None),
        )
        .all()
    )
    sent_count = 0

    for user in users:
        if not is_digest_due(user, current_utc):
            continue

        local_now = digest_local_datetime(user, current_utc)
        local_date = local_now.date()
        previous_sent_date = user.telegram_morning_digest_last_sent_date
        reservation_created = False
        try:
            message = build_morning_digest_message(
                db,
                user,
                target_date=local_date,
                current_local_time=local_now.time().replace(tzinfo=None),
            )
            reserved = (
                db.query(User)
                .filter(
                    User.id == user.id,
                    or_(
                        User.telegram_morning_digest_last_sent_date.is_(None),
                        User.telegram_morning_digest_last_sent_date != local_date,
                    ),
                )
                .update(
                    {
                        User.telegram_morning_digest_last_sent_date: local_date,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if reserved != 1:
                continue
            reservation_created = True

            send_message(
                TelegramReply(
                    chat_id=user.telegram_chat_id,
                    text=message,
                    reply_markup={
                        'inline_keyboard': [
                            [
                                {'text': '📅 Сегодня', 'callback_data': 'today'},
                                {'text': '📌 Задачи', 'callback_data': 'tasks'},
                            ],
                            [
                                {
                                    'text': '🌐 Открыть сайт',
                                    'url': settings.public_base_url
                                    or 'https://student-assistant-beby.onrender.com',
                                }
                            ],
                        ]
                    },
                )
            )
            sent_count += 1
        except Exception as error:
            db.rollback()
            if reservation_created:
                (
                    db.query(User)
                    .filter(
                        User.id == user.id,
                        User.telegram_morning_digest_last_sent_date == local_date,
                    )
                    .update(
                        {
                            User.telegram_morning_digest_last_sent_date: previous_sent_date,
                        },
                        synchronize_session=False,
                    )
                )
                db.commit()
            if isinstance(error, TelegramAPIError):
                logger.warning(
                    'Telegram morning digest delivery failed for user id %s.',
                    user.id,
                )
            else:
                logger.exception(
                    'Telegram morning digest processing failed for user id %s.',
                    user.id,
                )

    return sent_count


def process_deadline_reminders(
    db: Session,
    *,
    now_utc: datetime | None = None,
    send_message: Callable[[TelegramReply], None] = send_telegram_message,
) -> int:
    current_utc = now_utc or datetime.now(UTC)
    users = (
        db.query(User)
        .filter(
            User.telegram_deadline_reminders_enabled.is_(True),
            User.telegram_user_id.is_not(None),
            User.telegram_chat_id.is_not(None),
        )
        .all()
    )
    sent_count = 0

    for user in users:
        local_now = digest_local_datetime(user, current_utc).replace(
            tzinfo=None,
            second=0,
            microsecond=0,
        )
        reminder_hours = deadline_reminder_hours(user)
        tasks = (
            db.query(Task)
            .filter(
                Task.user_id == user.id,
                Task.is_completed.is_(False),
                Task.deadline.is_not(None),
                Task.deadline > local_now,
                Task.deadline <= local_now + timedelta(hours=reminder_hours),
            )
            .order_by(Task.deadline.asc())
            .all()
        )

        for task in tasks:
            date_key = deadline_reminder_date_key(task, reminder_hours)
            log = TelegramDeadlineReminderLog(
                user_id=user.id,
                task_id=task.id,
                reminder_hours=reminder_hours,
                reminder_date_key=date_key,
                sent_at=local_now,
            )
            db.add(log)
            try:
                db.commit()
                db.refresh(log)
            except IntegrityError:
                db.rollback()
                continue

            try:
                send_message(
                    TelegramReply(
                        chat_id=user.telegram_chat_id,
                        text=build_deadline_reminder_message(task, reminder_hours),
                        reply_markup={
                            'inline_keyboard': [
                                [
                                    {'text': '📌 Задачи', 'callback_data': 'tasks'},
                                    {
                                        'text': '✅ Закрыть задачу',
                                        'callback_data': f'done_task:{task.id}',
                                    },
                                ],
                                [
                                    {
                                        'text': '🌐 Открыть сайт',
                                        'url': settings.public_base_url
                                        or 'https://student-assistant-beby.onrender.com',
                                    }
                                ],
                            ]
                        },
                    )
                )
                sent_count += 1
            except Exception as error:
                db.rollback()
                delivery_log = db.get(TelegramDeadlineReminderLog, log.id)
                if delivery_log is not None:
                    db.delete(delivery_log)
                    db.commit()
                if isinstance(error, TelegramAPIError):
                    logger.warning(
                        'Telegram deadline reminder delivery failed for user id %s.',
                        user.id,
                    )
                else:
                    logger.exception(
                        'Telegram deadline reminder processing failed for user id %s.',
                        user.id,
                    )

    return sent_count


def run_scheduler(
    *,
    session_factory=SessionLocal,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        db = session_factory()
        try:
            try:
                process_due_digests(db)
            except Exception:
                db.rollback()
                logger.exception('Telegram digest scheduler iteration failed.')
            try:
                process_deadline_reminders(db)
            except Exception:
                db.rollback()
                logger.exception('Telegram deadline reminder iteration failed.')
        finally:
            db.close()
        sleep(settings.telegram_digest_check_interval_seconds)


def configure_logging() -> None:
    log_level = getattr(logging, settings.telegram_bot_log_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )


def main() -> int:
    configure_logging()
    if not settings.telegram_bot_token:
        print(
            'Telegram token is missing. Set TELEGRAM_BOT_TOKEN '
            'or TELEGRAM_BOT_API_TOKEN.',
            file=sys.stderr,
        )
        return 1

    run_migrations()
    print('Telegram notification scheduler started. Press Ctrl+C to stop.', flush=True)
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print('\nTelegram notification scheduler stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
