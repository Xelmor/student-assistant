"""Durable class preferences, occurrence reminders and one-shot snooze.

All state uses the existing TelegramState table. Delivery runs only from the
existing scheduler and reuses its retry/backoff transport.
"""
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import logging
import re

from ..models import TelegramState, User
from .telegram_day import TelegramCalendar, format_interval, has_complete_time
from .telegram_digest import digest_local_datetime, resolve_digest_timezone_name
from .telegram_now import _lesson_text
from .telegram_state import state_row

logger = logging.getLogger(__name__)
LEAD_MINUTES = (10, 15, 30, 60)
REMINDER_GRACE = timedelta(minutes=5)
SNOOZE_DELAY = timedelta(minutes=10)
SNOOZE_GRACE = timedelta(minutes=10)
MAX_SNOOZE_MOVE = timedelta(minutes=60)


def preferences(db, user):
    row = db.get(TelegramState, f'class-settings:{user.id}')
    data = row.data if row else {}
    lead = data.get('lead', 15)
    return {'enabled': data.get('enabled') is True,
            'lead': lead if lead in LEAD_MINUTES else 15}


def set_preferences(db, user, *, enabled=None, lead=None):
    row = state_row(db, f'class-settings:{user.id}')
    data = preferences(db, user)
    if enabled is not None:
        data['enabled'] = bool(enabled)
    if lead in LEAD_MINUTES:
        data['lead'] = lead
    row.data = data
    row.expires_at = datetime(9999, 1, 1)
    db.flush()
    return data


def button(text, action):
    return {'text': text, 'callback_data': action}


def settings_summary(db, user):
    pref = preferences(db, user)
    return f'🎓 Напоминания о парах: {"✅" if pref["enabled"] else "❌"}\n⏰ До пары: {pref["lead"]} мин'


def settings_view(db, user, *, choose_lead=False):
    pref = preferences(db, user)
    text = (f'🎓 <b>Напоминания о парах</b>\n\n'
            f'Статус: {"включены" if pref["enabled"] else "выключены"}\n'
            f'Напоминать за: {pref["lead"]} минут')
    if choose_lead:
        buttons = [button(f'{"✅ " if pref["lead"] == n else ""}{n} мин', f'class_lead:{n}') for n in LEAD_MINUTES]
        rows = [buttons[:2], buttons[2:], [button('← Назад', 'class_settings')]]
    else:
        rows = [[button('🔔 Выключить' if pref['enabled'] else '🔔 Включить',
                        'class_disable' if pref['enabled'] else 'class_enable')],
                [button('⏰ За сколько', 'class_lead')], [button('← Назад', 'settings')]]
    return text, {'inline_keyboard': rows}


def binding(user):
    return [user.telegram_user_id, user.telegram_chat_id,
            user.telegram_linked_at.isoformat() if user.telegram_linked_at else None]


def occurrence_id(lesson):
    return f'{lesson["type"]}:{lesson.get("schedule_item_id") or lesson.get("academic_event_id")}'


def occurrence_key(user, lesson, lead):
    identity = [user.id, occurrence_id(lesson), lesson['start'].isoformat(),
                lead, 'class-reminder', binding(user), resolve_digest_timezone_name(user)]
    token = sha256(repr(identity).encode()).hexdigest()[:32]
    return f'class-event:{user.id}:{token}'


def reminder_view(lesson, local_now, key, *, snooze=False):
    body = _lesson_text(lesson)
    if snooze:
        if lesson['start'] <= local_now:
            text = f'😴 Напоминание\n\n{body}\n\nЗанятие уже началось.'
        else:
            text = f'😴 Напоминание\n\n{body}\n\nНачало через {format_interval(lesson["start"] - local_now)}.'
        rows = [[button('📍 Сейчас', 'now')]]
    else:
        text = f'⏰ Через {format_interval(lesson["start"] - local_now)}\n\n{body}'
        rows = [[button('📍 Сейчас', 'now'), button('📅 Сегодня', 'today')],
                [button('😴 Напомнить через 10 мин', 'class_snooze:' + key.split(':')[-1])]]
    return text, {'inline_keyboard': rows}


def request_snooze(db, user, token, *, now_utc=None):
    if not re.fullmatch(r'[a-f0-9]{32}', token):
        return '⚠️ Напоминание недоступно.'
    key = f'class-event:{user.id}:{token}'
    if db.get(TelegramState, key) is None:
        return '⚠️ Напоминание недоступно.'
    row = state_row(db, key)
    data = dict(row.data)
    current = now_utc or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    now = current.astimezone(UTC).replace(tzinfo=None)
    if (data.get('binding') != binding(user) or not user.telegram_user_id
            or not preferences(db, user)['enabled'] or data.get('status') != 'sent'):
        return '⚠️ Напоминание недоступно.'
    if data.get('snooze_due'):
        return '⚠️ Это напоминание уже отложено.'
    if now >= datetime.fromisoformat(data['end_utc']):
        return '⚠️ Это занятие уже закончилось.'
    data.update(snooze_due=(now + SNOOZE_DELAY).isoformat(), snooze_status='pending')
    row.data = data
    db.flush()
    return '😴 Хорошо, напомню ещё раз через 10 минут.'


def _effective_lesson(db, user, data, local_now, *, snooze=False):
    # No separate override or recurrence rules: the same effective calendar as /today.
    calendar = TelegramCalendar(db, user, local_now)
    day = date.fromisoformat(data['day'])
    lesson = next((item for item in calendar.day(day).lessons
                   if occurrence_id(item) == data['occurrence'] and has_complete_time(item)), None)
    if not lesson:
        return None
    shift = abs(lesson['start'] - datetime.fromisoformat(data['start']))
    if shift > (MAX_SNOOZE_MOVE if snooze else timedelta(0)):
        return None
    return lesson


def process_class_reminders(db, *, now_utc=None, send_message, send_notification):
    """One scheduler pass. Database row locks serialize workers through send+commit."""
    from .telegram_bot import TelegramAPIError, TelegramReply

    def retryable_send(reply):
        try:
            send_message(reply)
        except TelegramAPIError:
            raise
        except Exception:
            # Unknown transport failures get the same durable, bounded retry as
            # network errors. Never persist an exception containing user data.
            raise TelegramAPIError(category='network') from None

    current = now_utc or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    now = current.astimezone(UTC).replace(tzinfo=None)
    ids = db.query(User.id).filter(User.telegram_user_id.isnot(None), User.telegram_chat_id > 0).all()
    sent = 0
    for (user_id,) in ids:
        try:
            user = db.get(User, user_id)
            if not preferences(db, user)['enabled']:
                db.commit()
                continue
            local = digest_local_datetime(user, current)
            wall = local.replace(tzinfo=None)
            lead = preferences(db, user)['lead']
            calendar = TelegramCalendar(db, user, wall)
            # Include tomorrow: a 00:10 lesson may be due the previous evening.
            for day in (wall.date(), (wall + timedelta(days=1)).date()):
                for lesson in calendar.day(day).lessons:
                    due = lesson['start'] - timedelta(minutes=lead)
                    if not has_complete_time(lesson) or not (due <= wall <= due + REMINDER_GRACE and wall < lesson['start']):
                        continue
                    row = state_row(db, occurrence_key(user, lesson, lead))
                    if not row.data:
                        row.data = {'user_id': user_id, 'binding': binding(user), 'lead': lead,
                                    'zone': resolve_digest_timezone_name(user),
                                    'occurrence': occurrence_id(lesson), 'day': day.isoformat(),
                                    'start': lesson['start'].isoformat(),
                                    'end_utc': lesson['end'].replace(tzinfo=local.tzinfo).astimezone(UTC).replace(tzinfo=None).isoformat(),
                                    'status': 'pending'}
                        row.expires_at = now + timedelta(days=8)
            db.commit()  # Persist pending work before attempting Telegram.
            keys = db.query(TelegramState.key).filter(
                TelegramState.key.startswith(f'class-event:{user_id}:'), TelegramState.expires_at > now,
            ).all()
            for (key,) in keys:
                try:
                    row = state_row(db, key)
                    data = dict(row.data)
                    snooze = data.get('status') == 'sent' and data.get('snooze_status') == 'pending'
                    if data.get('status') != 'pending' and not snooze:
                        db.commit()
                        continue
                    field = 'snooze_status' if snooze else 'status'
                    if snooze and now < datetime.fromisoformat(data['snooze_due']):
                        db.commit()
                        continue
                    # Hold consent lock through delivery, just like the other notifications.
                    db.refresh(user, with_for_update=True)
                    pref = preferences(db, user)
                    local = digest_local_datetime(user, current).replace(tzinfo=None)
                    valid = (bool(user.telegram_user_id) and user.telegram_chat_id and user.telegram_chat_id > 0
                             and data['binding'] == binding(user) and pref['enabled']
                             and data['zone'] == resolve_digest_timezone_name(user)
                             and (snooze or data['lead'] == pref['lead']))
                    lesson = _effective_lesson(db, user, data, local, snooze=snooze) if valid else None
                    stale = (now > datetime.fromisoformat(data['snooze_due']) + SNOOZE_GRACE if snooze else False)
                    if not lesson or stale or local >= (lesson['end'] if snooze else lesson['start']):
                        data[field] = 'cancelled'
                        row.data = data
                        db.commit()
                        continue
                    text, markup = reminder_view(lesson, local, key, snooze=snooze)
                    delivery = state_row(db, ('class-snooze-send:' if snooze else 'class-send:') + key.split(':')[-1])
                    if send_notification(db, delivery, key, TelegramReply(chat_id=user.telegram_chat_id, text=text, reply_markup=markup),
                                         retryable_send, user, now=now):
                        data[field] = 'sent'
                        row.data = data
                        sent += 1
                    db.commit()
                except Exception as error:
                    db.rollback()
                    logger.warning('Telegram stage=class user_id=%s category=%s', user_id, getattr(error, 'category', 'processing'))
        except Exception as error:
            db.rollback()
            logger.warning('Telegram stage=class user_id=%s category=%s', user_id, getattr(error, 'category', 'processing'))
    return sent
