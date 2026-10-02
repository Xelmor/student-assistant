"""Real calendar/database and scheduler tests; all time and Telegram I/O injected."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from app.models import AcademicEvent, Task, TelegramState, User
from app.services import telegram_class_reminders as reminders
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, clear_telegram_link, handle_telegram_update
from telegram_bot import scheduler
from test_telegram_now import DAY, MOSCOW, add_lesson, harness

NOW = datetime(2026, 9, 29, 5, 45, tzinfo=UTC)  # 08:45 Moscow


def setup(db, harness, *, lead=15, enabled=True, start='09:00', **kwargs):
    user = db.get(User, harness.first_user_id)
    reminders.set_preferences(db, user, enabled=enabled, lead=lead)
    item = add_lesson(db, harness, start=start, **kwargs)
    return user, item


def tick(harness, now=NOW, sender=None):
    with harness.SessionLocal() as db:
        return scheduler.process_class_reminders(db, now_utc=now, send_message=sender if sender is not None else lambda _: None)


def action(reply):
    return reply.reply_markup['inline_keyboard'][1][0]['callback_data']


def snooze(harness, reply, now=NOW, *, sender=7001, chat_id=8001):
    with harness.SessionLocal() as db, patch('app.services.telegram_class_reminders.datetime') as clock:
        clock.now.return_value = now
        clock.fromisoformat = datetime.fromisoformat
        return handle_telegram_update(db, harness._callback(action(reply), telegram_user_id=sender, chat_id=chat_id))


def send_first(harness, *, lead=15, now=NOW, **kwargs):
    with harness.SessionLocal() as db:
        setup(db, harness, lead=lead, **kwargs)
    sent = []
    assert tick(harness, now, sent.append) == 1
    return sent[0]


@pytest.mark.parametrize('lead', [10, 15, 30, 60])
def test_lead_times_and_exactly_once(harness, lead):
    now = NOW + timedelta(minutes=15-lead)
    reply = send_first(harness, lead=lead, now=now)
    assert f'Через {reminders.format_interval(timedelta(minutes=lead))}' in reply.text
    assert '09:00–10:30 · Ауд. 301' in reply.text
    assert tick(harness, now) == 0
    assert tick(harness, now + timedelta(minutes=1)) == 0
    assert reply.reply_markup['inline_keyboard'][0] == [
        {'text': '📍 Сейчас', 'callback_data': 'now'}, {'text': '📅 Сегодня', 'callback_data': 'today'}]
    assert len(action(reply).encode()) <= 64


@pytest.mark.parametrize('offset,expected', [(-1, 0), (1, 1), (5, 1), (6, 0), (15, 0)])
def test_scheduler_grace_and_start_boundary(harness, offset, expected):
    with harness.SessionLocal() as db:
        setup(db, harness)
    assert tick(harness, NOW + timedelta(minutes=offset)) == expected


def test_disabled_and_default_settings(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        assert reminders.preferences(db, user) == {'enabled': False, 'lead': 15}
        setup(db, harness, enabled=False)
    assert tick(harness) == 0


@pytest.mark.parametrize('zone,instant', [('Europe/Moscow', NOW), ('Asia/Vladivostok', datetime(2026, 9, 28, 22, 45, tzinfo=UTC))])
def test_timezone_independent_of_host(harness, monkeypatch, zone, instant):
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    with harness.SessionLocal() as db:
        user, _ = setup(db, harness)
        user.telegram_morning_digest_timezone = zone
        db.commit()
    assert tick(harness, instant) == 1


def test_midnight_looks_at_tomorrow(harness):
    now = datetime(2026, 9, 28, 20, 55, tzinfo=UTC)  # Monday 23:55; Tuesday 00:10
    send_first(harness, now=now, start='00:10', end='01:40')


def test_no_empty_room_and_escape(harness):
    reply = send_first(harness, title='БД <&>', room=None)
    assert 'Ауд.' not in reply.text and 'БД &lt;&amp;&gt;' in reply.text


def override(db, harness, *, moved=False):
    db.add(AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY))
    if moved:
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Новая пара', event_type='changed_class',
                             event_date=DAY, start_time=time(11), end_time=time(12, 30), room='777'))
    db.commit()


@pytest.mark.parametrize('moved', [False, True])
def test_cancelled_and_moved_effective_calendar(harness, moved):
    with harness.SessionLocal() as db:
        setup(db, harness)
        override(db, harness, moved=moved)
    sent = []
    assert tick(harness, NOW, sent.append) == 0
    assert tick(harness, NOW + timedelta(hours=2), sent.append) == int(moved)
    if moved:
        assert 'Новая пара' in sent[0].text and '11:00–12:30 · Ауд. 777' in sent[0].text


def test_failure_is_pending_then_retried(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
    sender = Mock(side_effect=[TelegramAPIError(category='network'), None])
    assert tick(harness, NOW, sender) == 0
    with harness.SessionLocal() as db:
        row = db.query(TelegramState).filter(TelegramState.key.startswith('class-event:')).one()
        assert row.data['status'] == 'pending'
    assert tick(harness, NOW + timedelta(seconds=30), sender) == 0
    assert tick(harness, NOW + timedelta(minutes=1), sender) == 1
    assert sender.call_count == 2
    assert tick(harness, NOW + timedelta(minutes=2), sender) == 0


def test_pending_retry_survives_discovery_window(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    assert tick(harness, NOW + timedelta(minutes=6)) == 1


def test_blocked_user_does_not_stop_other_user(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        other.telegram_morning_digest_timezone = 'Europe/Moscow'
        reminders.set_preferences(db, other, enabled=True)
        add_lesson(db, harness, user_id=other.id)
    sent = []
    def send(reply):
        sent.append(reply.chat_id)
        if reply.chat_id == 8001:
            raise TelegramAPIError(category='blocked')
    assert tick(harness, sender=send) == 1
    assert tick(harness, NOW + timedelta(minutes=1), send) == 0
    assert sent == [8001, 8002]


def test_two_workers_send_once(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
    sent = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: tick(harness, sender=sent.append), range(2))) == 1
    assert len(sent) == 1


def test_snooze_once_after_ten_minutes_without_mutating_schedule_or_task(harness):
    reply = send_first(harness)
    with harness.SessionLocal() as db:
        db.add(Task(user_id=harness.first_user_id, title='Задача', deadline=datetime(2026, 9, 30, 18)))
        db.commit()
    assert 'через 10 минут' in snooze(harness, reply).text
    assert 'уже отложено' in snooze(harness, reply).text
    sent = []
    assert tick(harness, NOW + timedelta(minutes=9, seconds=59), sent.append) == 0
    assert tick(harness, NOW + timedelta(minutes=10), sent.append) == 1
    assert '😴 Напоминание' in sent[0].text and 'Начало через 5 мин.' in sent[0].text
    assert tick(harness, NOW + timedelta(minutes=11), sent.append) == 0
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert task.deadline == datetime(2026, 9, 30, 18) and not task.is_completed
        assert reminders.preferences(db, db.get(User, harness.first_user_id)) == {'enabled': True, 'lead': 15}
        assert reminders.TelegramCalendar(db, db.get(User, harness.first_user_id), NOW).day(DAY).lessons[0]['start'].time() == time(9)


def test_snooze_after_lesson_started(harness):
    reply = send_first(harness, lead=10, now=NOW + timedelta(minutes=5))
    snooze(harness, reply, NOW + timedelta(minutes=5))
    sent = []
    assert tick(harness, NOW + timedelta(minutes=15), sent.append) == 1
    assert 'уже началось' in sent[0].text
    assert sent[0].reply_markup == {'inline_keyboard': [[{'text': '📍 Сейчас', 'callback_data': 'now'}]]}


@pytest.mark.parametrize('change', ['cancel', 'delete', 'move', 'large_move', 'unlink', 'disable', 'expired'])
def test_snooze_revalidates_current_data(harness, change):
    reply = send_first(harness)
    snooze(harness, reply)
    from app.models import ScheduleItem
    with harness.SessionLocal() as db:
        item = db.query(ScheduleItem).one()
        user = db.get(User, harness.first_user_id)
        if change == 'cancel':
            override(db, harness)
        elif change == 'delete':
            db.delete(item)
        elif change in {'move', 'large_move'}:
            item.start_time = time(9, 10) if change == 'move' else time(13)
            item.end_time = time(10, 40) if change == 'move' else time(14, 30)
            item.room = '202'
        elif change == 'unlink':
            clear_telegram_link(user)
        elif change == 'disable':
            reminders.set_preferences(db, user, enabled=False)
        db.commit()
    sent = []
    now = NOW + timedelta(minutes=25 if change == 'expired' else 10)
    result = tick(harness, now, sent.append)
    if change == 'move':
        # Both the new effective occurrence reminder and the snooze may be due.
        snoozes = [item for item in sent if '😴' in item.text]
        assert len(snoozes) == 1
        assert '09:10–10:40 · Ауд. 202' in snoozes[0].text
        assert 'Начало через 15 мин.' in snoozes[0].text
    else:
        assert result == 0


def test_unlink_suppresses_new_reminders_and_old_callback(harness):
    reply = send_first(harness)
    with harness.SessionLocal() as db:
        clear_telegram_link(db.get(User, harness.first_user_id))
        db.commit()
    assert tick(harness, NOW + timedelta(days=7)) == 0
    assert 'подключ' in snooze(harness, reply).text.lower()


def test_foreign_snooze_and_group_are_rejected(harness):
    reply = send_first(harness)
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        reminders.set_preferences(db, other, enabled=True)
        db.commit()
    assert 'недоступно' in snooze(harness, reply, sender=7002, chat_id=8002).text
    with harness.SessionLocal() as db:
        update = harness._callback(action(reply), chat_id=-100)
        update['callback_query']['message']['chat']['type'] = 'group'
        assert 'личный чат' in handle_telegram_update(db, update).text
        row = db.query(TelegramState).filter(TelegramState.key.startswith('class-event:')).one()
        assert 'snooze_due' not in row.data


def test_settings_callbacks_persist_and_users_independent(harness):
    def call(action):
        with harness.SessionLocal() as db:
            return handle_telegram_update(db, harness._callback(action))
    assert '❌' in call('settings').text
    assert 'выключены' in call('class_settings').text
    assert 'включены' in call('class_enable').text
    # Enable is explicit: replaying the same button does not toggle it off.
    assert 'включены' in call('class_enable').text
    for lead in (10, 15, 30, 60):
        reply = call(f'class_lead:{lead}')
        assert f'✅ {lead} мин' in str(reply.reply_markup)
        with harness.SessionLocal() as db:
            assert reminders.preferences(db, db.get(User, harness.first_user_id)) == {'enabled': True, 'lead': lead}
            assert reminders.preferences(db, db.get(User, harness.second_user_id)) == {'enabled': False, 'lead': 15}
    assert 'выключены' in call('class_disable').text
    assert '60 минут' in call('class_lead:999').text
    assert call('class_settings').reply_markup['inline_keyboard'][-1][0]['callback_data'] == 'settings'
    assert call('class_lead').reply_markup['inline_keyboard'][-1][0]['callback_data'] == 'class_settings'
    assert len(BOT_COMMANDS) == 6


def test_restart_subprocess_preserves_settings_dedup_and_snooze(harness):
    reply = send_first(harness)
    snooze(harness, reply)
    script = '''
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram_bot.scheduler import process_class_reminders
engine = create_engine(sys.argv[1])
sent = []
with Session(engine) as db:
    assert process_class_reminders(db, now_utc=datetime(2026,9,29,5,46,tzinfo=UTC), send_message=sent.append) == 0
    assert process_class_reminders(db, now_utc=datetime(2026,9,29,5,55,tzinfo=UTC), send_message=sent.append) == 1
    assert process_class_reminders(db, now_utc=datetime(2026,9,29,5,56,tzinfo=UTC), send_message=sent.append) == 0
assert len(sent) == 1 and '😴' in sent[0].text
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_existing_scheduler_tick_calls_class_reminders(harness):
    with harness.SessionLocal() as db, patch.object(scheduler, 'retry_pending_replies'), patch.object(scheduler, 'process_due_digests'), patch.object(scheduler, 'process_deadline_reminders'), patch.object(scheduler, 'process_class_reminders') as process:
        scheduler.scheduler_tick(db)
        process.assert_called_once_with(db)


def test_unknown_send_failure_has_bounded_durable_retries(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
    sender = Mock(side_effect=RuntimeError('simulated transport failure'))
    for minute in range(8):
        assert tick(harness, NOW + timedelta(minutes=minute), sender) == 0
    assert sender.call_count == 5
    with harness.SessionLocal() as db:
        delivery = db.query(TelegramState).filter(TelegramState.key.startswith('class-send:')).one()
        assert delivery.data['terminal'] and not delivery.data.get('sent')


def test_snooze_failure_retries_then_sends_once(harness):
    reply = send_first(harness)
    snooze(harness, reply)
    sender = Mock(side_effect=[TelegramAPIError(category='rate_limit', retry_after=120), None])
    assert tick(harness, NOW + timedelta(minutes=10), sender) == 0
    assert tick(harness, NOW + timedelta(minutes=11), sender) == 0
    assert tick(harness, NOW + timedelta(minutes=12), sender) == 1
    assert tick(harness, NOW + timedelta(minutes=13), sender) == 0
    assert sender.call_count == 2


def test_workers_send_snooze_once(harness):
    reply = send_first(harness)
    snooze(harness, reply)
    sent = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: tick(harness, NOW + timedelta(minutes=10), sent.append), range(2))) == 1
    assert len(sent) == 1


def test_old_link_binding_does_not_send_snooze_after_relink(harness):
    reply = send_first(harness)
    snooze(harness, reply)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        clear_telegram_link(user)
        user.telegram_user_id, user.telegram_chat_id = 7001, 8001
        user.telegram_linked_at = NOW.replace(tzinfo=None) + timedelta(minutes=1)
        db.commit()
    assert tick(harness, NOW + timedelta(minutes=10)) == 0
    assert 'недоступно' in snooze(harness, reply).text


def test_pending_reminder_rechecks_cancellation_before_retry(harness):
    with harness.SessionLocal() as db:
        setup(db, harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    with harness.SessionLocal() as db:
        override(db, harness)
    assert tick(harness, NOW + timedelta(minutes=1)) == 0


def test_settings_require_linked_private_chat(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        update = harness._callback('class_enable', chat_id=-100)
        update['callback_query']['message']['chat']['type'] = 'supergroup'
        assert 'личный чат' in handle_telegram_update(db, update).text
        assert not reminders.preferences(db, user)['enabled']
        clear_telegram_link(user)
        db.commit()
        assert 'подключ' in handle_telegram_update(db, harness._callback('class_enable')).text.lower()
        assert not reminders.preferences(db, user)['enabled']


def test_reminder_navigation_uses_existing_now_and_today(harness):
    reply = send_first(harness)
    from app.services.telegram_digest import digest_local_datetime
    with harness.SessionLocal() as db, patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW)), patch('app.services.telegram_now.digest_local_datetime', side_effect=lambda user, now=None: digest_local_datetime(user, NOW)):
        now_reply = handle_telegram_update(db, harness._callback(reply.reply_markup['inline_keyboard'][0][0]['callback_data']))
        assert 'Учебный день ещё не начался' in now_reply.text and 'Математика' in now_reply.text
        with patch('app.services.telegram_bot.build_today_summary', return_value='Сегодня: расписание') as today:
            today_reply = handle_telegram_update(db, harness._callback(reply.reply_markup['inline_keyboard'][0][1]['callback_data']))
            today.assert_called_once()
            assert today_reply.text == 'Сегодня: расписание'


def test_changed_room_or_end_does_not_duplicate_original(harness):
    send_first(harness)
    from app.models import ScheduleItem
    with harness.SessionLocal() as db:
        item = db.query(ScheduleItem).one()
        item.end_time, item.room = time(10, 40), '202'
        db.commit()
    assert tick(harness, NOW + timedelta(minutes=1)) == 0
