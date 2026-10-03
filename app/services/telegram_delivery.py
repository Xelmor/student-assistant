"""Transactional command execution with a durable reply outbox; no network on import."""
from dataclasses import asdict
from datetime import timedelta
import logging

from sqlalchemy.exc import IntegrityError

from ..models import TelegramUpdate, User
from .telegram_bot import TelegramAPIError, TelegramReply, handle_telegram_update, send_telegram_message
from .telegram_state import state_row, utcnow

logger = logging.getLogger(__name__)


def process_update(db, update, *, send_message=send_telegram_message):
    update_id = update.get('update_id')
    if type(update_id) is not int or not 0 <= update_id < 2**63:
        raise ValueError('invalid update_id')
    existing = db.get(TelegramUpdate, update_id)
    if existing is None:
        now = utcnow()
        try:
            # Uniqueness serializes concurrent deliveries of this exact update.
            record = TelegramUpdate(update_id=update_id, created_at=now, available_at=now)
            db.add(record)
            db.flush()
            db.info['telegram_atomic'] = True
            reply = handle_telegram_update(db, update)
            if not db.in_transaction() or record not in db:
                raise RuntimeError('Command transaction was rolled back')
            record.reply = asdict(reply) if reply else None
            snapshot = db.info.get('telegram_task_snapshot')
            if record.reply is not None and snapshot is not None:
                record.reply = {**record.reply, '_task_snapshot': snapshot}
            message = update.get('callback_query') or update.get('message') or {}
            sender = message.get('from', {}) if isinstance(message, dict) else {}
            sender_id = sender.get('id') if isinstance(sender, dict) else None
            record.telegram_user_id = sender_id if type(sender_id) is int and 0 < sender_id < 2**63 else None
            user = db.query(User).filter_by(telegram_user_id=record.telegram_user_id).first() if record.telegram_user_id else None
            record.user_id = user.id if user and reply and reply.chat_id == user.telegram_chat_id else None
            if record.user_id:
                record.reply = {**record.reply, '_linked_at': user.telegram_linked_at.isoformat() if user.telegram_linked_at else None}
            record.status = 'pending' if reply else 'sent'
            db.commit()
            logger.info('Telegram stage=stored update_id=%s', update_id)
        except IntegrityError:
            db.rollback()
            if db.get(TelegramUpdate, update_id) is None:
                raise RuntimeError('Telegram transaction conflict') from None
        except Exception:
            db.rollback()
            logger.error('Telegram stage=command update_id=%s category=processing_failed', update_id)
            raise
        finally:
            db.info.pop('telegram_atomic', None)
            db.info.pop('telegram_task_snapshot', None)
    deliver_reply(db, update_id, send_message=send_message)


def deliver_reply(db, update_id, *, send_message=send_telegram_message):
    now = utcnow()
    candidate = db.get(TelegramUpdate, update_id)
    text_length = len((candidate.reply or {}).get('text', '')) if candidate else 0
    lease_seconds = max(180, 60 + (text_length // 1900 + 1) * 12)
    claimed = db.query(TelegramUpdate).filter(
        TelegramUpdate.update_id == update_id,
        TelegramUpdate.status == 'pending', TelegramUpdate.available_at <= now,
    ).update({TelegramUpdate.available_at: now + timedelta(seconds=lease_seconds),
              TelegramUpdate.attempts: TelegramUpdate.attempts + 1}, synchronize_session=False)
    db.commit()
    if not claimed:
        return  # Already delivered, or durably reserved for another worker.
    record = db.get(TelegramUpdate, update_id)
    db.refresh(record)
    if record.created_at < now - timedelta(hours=24):
        record.status, record.reply = 'expired', None
        db.commit()
        return
    if record.user_id:
        user = db.get(User, record.user_id)
        if user:
            db.refresh(user, with_for_update=True)
        db.refresh(record, with_for_update=True)
        if record.status != 'pending' or not record.reply:
            db.commit()
            return
        if (not user or user.telegram_user_id != record.telegram_user_id
                or user.telegram_chat_id != record.reply['chat_id']
                or record.reply.get('_linked_at') != (user.telegram_linked_at.isoformat() if user.telegram_linked_at else None)):
            record.status, record.reply = 'cancelled', None
            db.commit()
            return
    # A previous sender may finish while this worker waits for the owner lock.
    db.refresh(record, with_for_update=True)
    if record.status != 'pending' or not record.reply:
        db.commit()
        return
    payload = dict(record.reply)
    payload.pop('_linked_at', None)
    snapshot = payload.pop('_task_snapshot', None)
    try:
        send_message(TelegramReply(**payload))
    except TelegramAPIError as error:
        record.error_category = error.category
        record.available_at = now + timedelta(seconds=max(3, error.retry_after or 3))
        if not error.retryable or record.attempts >= 5:
            record.status, record.reply = 'failed', None
        db.commit()
        logger.warning('Telegram stage=send update_id=%s category=%s', update_id, error.category)
        raise
    except Exception:
        # Keep the durable lease: unknown delivery outcome may be retried after expiry.
        db.rollback()
        record = db.get(TelegramUpdate, update_id)
        record.error_category = 'unexpected'
        if record.attempts >= 5:
            record.status, record.reply = 'failed', None
        db.commit()
        logger.error('Telegram stage=send update_id=%s category=unexpected', update_id)
        raise RuntimeError('Telegram delivery failed') from None
    if snapshot is not None:
        row = state_row(db, f'tasks:{snapshot["user_id"]}')
        row.data = {'ids': snapshot['ids']}
        row.expires_at = utcnow() + timedelta(minutes=30)
    record.status, record.reply = 'sent', None
    record.error_category = None
    db.commit()
    logger.info('Telegram stage=sent update_id=%s', update_id)


def retry_pending_replies(db, *, send_message=send_telegram_message):
    ids = db.query(TelegramUpdate.update_id).filter(
        TelegramUpdate.status == 'pending', TelegramUpdate.available_at <= utcnow(),
    ).order_by(TelegramUpdate.update_id).limit(50).all()
    for (update_id,) in ids:
        try:
            deliver_reply(db, update_id, send_message=send_message)
        except Exception:
            db.rollback()
            logger.warning('Telegram stage=reply_retry update_id=%s category=retry_failed', update_id)
