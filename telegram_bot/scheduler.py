from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.migrations import run_migrations
from app.models import Task, TelegramDeadlineReminderLog, TelegramState, User
from app.services.telegram_bot import DEFAULT_SITE_URL, TelegramAPIError, TelegramReply, send_telegram_message
from app.services.telegram_delivery import retry_pending_replies
from app.services.telegram_digest import build_morning_digest_message, digest_local_datetime, digest_send_time
from app.services.telegram_notifications import build_deadline_reminder_message, deadline_reminder_date_key, deadline_reminder_hours
from app.services.telegram_state import state_row, utcnow
from app.services.telegram_task_views import task_button
from app.services import telegram_class_reminders, telegram_evening_digest, telegram_weekly_digest

logger = logging.getLogger(__name__)
# After downtime, only today's digest in the first two hours and future deadlines.
DIGEST_GRACE = timedelta(hours=2)


def is_digest_due(user: User, now_utc: datetime | None = None) -> bool:
    if not user.telegram_morning_digest_enabled or user.telegram_user_id is None or user.telegram_chat_id is None:
        return False
    local = digest_local_datetime(user, now_utc)
    due = datetime.combine(local.date(), digest_send_time(user))
    return (user.telegram_morning_digest_last_sent_date != local.date()
            and timedelta(0) <= local.replace(tzinfo=None) - due <= DIGEST_GRACE)


def _keyboard(task_id=None, *, db=None, task=None):
    if db is not None and task is not None:
        return {'inline_keyboard': [
            [task_button(db, task, '✅ Выполнено', 'task_done'), task_button(db, task, '⏰ Перенести', 'task_reschedule')],
            [task_button(db, task, '✏️ Изменить', 'task_edit')],
            [{'text': '📌 Все задачи', 'callback_data': 'tasks'}],
        ]}
    second = ({'text': '✅ Закрыть задачу', 'callback_data': f'done_task:{task_id}'}
              if task_id is not None else {'text': '📅 Сегодня', 'callback_data': 'today'})
    return {'inline_keyboard': [
        [{'text': '📌 Задачи', 'callback_data': 'tasks'}, second],
        [{'text': '🌐 Открыть сайт', 'url': settings.public_base_url or DEFAULT_SITE_URL}],
    ]}


def _send_notification(db, row, key, reply, send_message, user, *, now=None):
    now = now or utcnow()
    binding = f'{user.telegram_user_id}:{user.telegram_linked_at}:' + sha256(settings.telegram_bot_token.encode()).hexdigest()
    if row.data.get('binding') == binding and row.data.get('error') in {'blocked', 'invalid_token', 'chat_not_found', 'missing_token'}:
        return False
    data = row.data if row.data.get('delivery') == key else {}
    if data.get('terminal') or (data and row.expires_at > now):
        return False
    attempts = data.get('attempts', 0) + 1
    try:
        send_message(reply)
    except TelegramAPIError as error:
        row.data = {'delivery': key, 'attempts': attempts,
                    'terminal': not error.retryable or attempts >= 5,
                    'error': error.category, 'binding': binding}
        row.expires_at = now + timedelta(seconds=max(60, error.retry_after or 0))
        db.commit()
        logger.warning('Telegram stage=notification category=%s', error.category)
        return False
    row.data = {'delivery': key, 'attempts': attempts, 'terminal': True, 'sent': True}
    return True


def process_due_digests(db: Session, *, now_utc=None, send_message=send_telegram_message) -> int:
    current = now_utc or datetime.now(UTC)
    ids = db.query(User.id).filter(User.telegram_morning_digest_enabled.is_(True)).all()
    sent = 0
    for (user_id,) in ids:
        try:
            # Held through confirmed send + log commit. Crash releases the DB lock.
            lock = state_row(db, f'digest-lock:{user_id}')
            user = db.get(User, user_id)
            db.refresh(user, with_for_update=True)
            if not is_digest_due(user, current):
                db.commit()
                continue
            local = digest_local_datetime(user, current)
            message = build_morning_digest_message(db, user, target_date=local.date(), current_local_time=local.time().replace(tzinfo=None))
            db.refresh(user, with_for_update=True)  # Recheck consent immediately before network send.
            if not is_digest_due(user, current):
                db.commit()
                continue
            delivery_key = f'{local.date()}:{user.telegram_linked_at}'
            if not _send_notification(db, lock, delivery_key, TelegramReply(chat_id=user.telegram_chat_id, text=message, reply_markup=_keyboard()), send_message, user):
                db.commit()
                continue
            user.telegram_morning_digest_last_sent_date = local.date()
            db.commit()
            sent += 1
        except Exception as error:
            db.rollback()
            logger.warning('Telegram stage=digest user_id=%s category=%s', user_id, getattr(error, 'category', 'processing'))
    return sent


def process_deadline_reminders(db: Session, *, now_utc=None, send_message=send_telegram_message) -> int:
    current = now_utc or datetime.now(UTC)
    ids = db.query(User.id).filter(User.telegram_deadline_reminders_enabled.is_(True)).all()
    sent = 0
    for (user_id,) in ids:
        user = db.get(User, user_id)
        local_now = digest_local_datetime(user, current).replace(tzinfo=None, second=0, microsecond=0)
        task_ids = db.query(Task.id).filter(
            Task.user_id == user_id, Task.is_completed.is_(False),
            Task.deadline > local_now, Task.deadline <= local_now + timedelta(hours=24),
        ).order_by(Task.deadline).all()
        user_sent = 0
        for (task_id,) in task_ids:
            if user_sent >= 3:
                break  # Catch-up is limited to three future deadlines per user/tick.
            try:
                lock = state_row(db, f'deadline-lock:{user_id}:{task_id}')
                user = db.get(User, user_id)
                db.refresh(user, with_for_update=True)
                task = db.get(Task, task_id)
                if task is not None:
                    db.refresh(task, with_for_update=True)
                if not task or task.is_completed or not task.deadline or not user.telegram_deadline_reminders_enabled or user.telegram_user_id is None or user.telegram_chat_id is None:
                    db.commit()
                    continue
                local = digest_local_datetime(user, current).replace(tzinfo=None, second=0, microsecond=0)
                hours = deadline_reminder_hours(user)
                if not local < task.deadline <= local + timedelta(hours=hours):
                    db.commit()
                    continue
                key = deadline_reminder_date_key(task, hours)
                if db.query(TelegramDeadlineReminderLog.id).filter_by(user_id=user_id, task_id=task_id, reminder_hours=hours, reminder_date_key=key).first():
                    db.commit()
                    continue
                if not _send_notification(db, lock, f'{key}:{user.telegram_linked_at}', TelegramReply(chat_id=user.telegram_chat_id, text=build_deadline_reminder_message(task, hours, user=user), reply_markup=_keyboard(task_id, db=db, task=task)), send_message, user):
                    db.commit()
                    continue
                db.add(TelegramDeadlineReminderLog(user_id=user_id, task_id=task_id, reminder_hours=hours, reminder_date_key=key, sent_at=local))
                db.commit()
                sent += 1
                user_sent += 1
            except Exception as error:
                db.rollback()
                logger.warning('Telegram stage=deadline user_id=%s category=%s', user_id, getattr(error, 'category', 'processing'))
    return sent


def process_class_reminders(db, *, now_utc=None, send_message=send_telegram_message):
    return telegram_class_reminders.process_class_reminders(
        db, now_utc=now_utc, send_message=send_message, send_notification=_send_notification,
    )


def _process_periodic_digest(db, *, kind, is_due, delivery_key, build_message, markup, now_utc, send_message):
    """Deliver once per period key with the shared durable notification retry."""

    current = now_utc or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    now = current.astimezone(UTC).replace(tzinfo=None)
    sent = 0
    ids = db.query(User.id).join(
        TelegramState, TelegramState.key == f'{kind}-settings:' + cast(User.id, String),
    ).filter(User.telegram_user_id.isnot(None), User.telegram_chat_id > 0,
             TelegramState.data['enabled'].as_boolean().is_(True)).all()

    def retryable_send(reply):
        try:
            send_message(reply)
        except TelegramAPIError:
            raise
        except Exception:
            raise TelegramAPIError(category='network') from None

    for (user_id,) in ids:
        try:
            user = db.get(User, user_id)
            if not is_due(db, user, current):
                db.commit()
                continue
            # Serialize preference changes and concurrent sends, then refresh consent.
            state_row(db, f'{kind}-settings:{user_id}')
            db.refresh(user, with_for_update=True)
            if not is_due(db, user, current):
                db.commit()
                continue
            key = delivery_key(user, current)
            delivery = state_row(db, key)
            if delivery.data.get('sent'):
                db.commit()
                continue
            text = build_message(db, user, now_utc=current)
            if _send_notification(db, delivery, key, TelegramReply(chat_id=user.telegram_chat_id, text=text, reply_markup=markup(user, current)),
                                 retryable_send, user, now=now):
                sent += 1
            db.commit()
        except Exception as error:
            db.rollback()
            logger.warning('Telegram stage=%s user_id=%s category=%s', kind, user_id, getattr(error, 'category', 'processing'))
    return sent


def process_evening_digests(db, *, now_utc=None, send_message=send_telegram_message):
    return _process_periodic_digest(
        db, kind='evening', is_due=telegram_evening_digest.is_due,
        delivery_key=lambda user, current: f'evening-digest:{user.id}:{digest_local_datetime(user, current).date()}',
        build_message=telegram_evening_digest.build_evening_digest_message,
        markup=lambda user, current: telegram_evening_digest.digest_keyboard(),
        now_utc=now_utc, send_message=send_message,
    )


def process_weekly_digests(db, *, now_utc=None, send_message=send_telegram_message):
    return _process_periodic_digest(
        db, kind='weekly', is_due=telegram_weekly_digest.is_due,
        delivery_key=telegram_weekly_digest.delivery_key,
        build_message=telegram_weekly_digest.automatic_message,
        markup=telegram_weekly_digest.automatic_keyboard,
        now_utc=now_utc, send_message=send_message,
    )


def scheduler_tick(db):
    row = state_row(db, 'scheduler-heartbeat')
    row.data = {'started_at': utcnow().isoformat(), 'state': 'running'}
    row.expires_at = utcnow() + timedelta(seconds=max(180, settings.telegram_digest_check_interval_seconds * 3))
    db.commit()
    retry_pending_replies(db)
    process_due_digests(db)
    process_deadline_reminders(db)
    process_class_reminders(db)
    process_evening_digests(db)
    process_weekly_digests(db)
    row = state_row(db, 'scheduler-heartbeat')
    row.data = {'completed_at': utcnow().isoformat(), 'state': 'completed'}
    row.expires_at = utcnow() + timedelta(seconds=max(180, settings.telegram_digest_check_interval_seconds * 3))
    db.commit()


def run_scheduler(*, session_factory=SessionLocal, sleep: Callable[[float], None] = time.sleep):
    while True:
        with session_factory() as db:
            try:
                scheduler_tick(db)
            except Exception:
                db.rollback()
                logger.error('Telegram stage=scheduler category=iteration_failed')
        sleep(settings.telegram_digest_check_interval_seconds)


def main() -> int:
    logging.basicConfig(level=getattr(logging, settings.telegram_bot_log_level, logging.INFO))
    if not settings.telegram_bot_token:
        print('Telegram token is missing or Telegram is disabled.', file=sys.stderr)
        return 1
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    run_migrations()
    print('Telegram notification scheduler started. Press Ctrl+C to stop.', flush=True)
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print('\nTelegram notification scheduler stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
