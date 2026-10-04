"""Effective schedule and Telegram consumers share the real calendar events."""
from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.models import AcademicEvent, User
from app.services.calendar_service import build_calendar_event_map, effective_schedule_for_day
from app.services.telegram_bot import build_tomorrow_message, build_week_message
from app.services.telegram_class_reminders import set_preferences
from app.services.telegram_digest import build_morning_digest_message
from app.services.telegram_now import build_now_message
from app.services.telegram_today import build_today_summary
from telegram_bot.scheduler import process_class_reminders, process_due_digests
from test_telegram_now import DAY, add_lesson, harness


def replacement_day(db, harness, count=1, day=DAY):
    add_lesson(db, harness, title='Старая пара', day=day)
    db.add(AcademicEvent(user_id=harness.first_user_id, title='Замена дня',
                         event_type='day_override', event_date=day))
    replacements = [AcademicEvent(
        user_id=harness.first_user_id, title=f'Замена {index + 1}',
        event_type='changed_class', event_date=day,
        start_time=time(11 + index * 2), end_time=time(12 + index * 2, 30), room='777',
    ) for index in range(count)]
    db.add_all(replacements)
    db.commit()
    return db.get(User, harness.first_user_id), replacements


@pytest.mark.parametrize('count', [0, 1, 3])
def test_override_keeps_only_replacements_in_calendar_order(harness, count):
    with harness.SessionLocal() as db:
        user, replacements = replacement_day(db, harness, count)
        lessons = effective_schedule_for_day(db, user, DAY)
        assert [lesson['academic_event_id'] for lesson in lessons] == [item.id for item in replacements]
        assert len(lessons) == count
        assert all(lesson['type'] == 'schedule-change' for lesson in lessons)
        calendar = build_calendar_event_map(user, db, DAY.year, DAY.month)['event_map'][DAY]
        assert lessons == [event for event in calendar if event['type'] == 'schedule-change']


def test_moved_time_and_deleted_replacement_are_read_fresh(harness):
    with harness.SessionLocal() as db:
        user, (replacement,) = replacement_day(db, harness)
        replacement.start_time, replacement.end_time = time(14), time(15, 30)
        db.commit()
        lesson, = effective_schedule_for_day(db, user, DAY)
        assert (lesson['start'].time(), lesson['end'].time()) == (time(14), time(15, 30))
        # Calendar cancellation removes the AcademicEvent; there is no separate
        # cancelled flag on this model. Keep the day_override in place.
        db.delete(replacement)
        db.commit()
        assert effective_schedule_for_day(db, user, DAY) == []
        assert 'На сегодня ничего не запланировано' in build_morning_digest_message(
            db, user, target_date=DAY, current_local_time=time(8))


def test_replacements_are_not_suppressed_by_recurring_term_boundary(harness):
    with harness.SessionLocal() as db:
        summer = DAY.replace(month=6)
        user, _ = replacement_day(db, harness, day=summer)
        assert len(effective_schedule_for_day(db, user, summer)) == 1


def test_other_users_replacement_is_not_in_effective_schedule(harness):
    with harness.SessionLocal() as db:
        user, _ = replacement_day(db, harness, 0)
        db.add(AcademicEvent(user_id=harness.second_user_id, title='Чужая замена',
                             event_type='changed_class', event_date=DAY,
                             start_time=time(11), end_time=time(12)))
        db.commit()
        assert effective_schedule_for_day(db, user, DAY) == []


def test_changed_class_without_override_augments_regular_calendar(harness):
    with harness.SessionLocal() as db:
        user, _ = replacement_day(db, harness)
        override = db.query(AcademicEvent).filter_by(user_id=user.id, event_type='day_override').one()
        db.delete(override)
        db.commit()
        lessons = effective_schedule_for_day(db, user, DAY)
        assert [lesson['title'] for lesson in lessons] == ['Старая пара', 'Замена 1']


@pytest.mark.parametrize('zone', ['Europe/Moscow', 'Asia/Vladivostok'])
def test_now_today_digest_and_reminder_use_replacement_in_user_timezone(harness, monkeypatch, zone):
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    with harness.SessionLocal() as db:
        user, (replacement,) = replacement_day(db, harness)
        # Early local lesson lies on the preceding UTC day in both timezones.
        replacement.start_time, replacement.end_time = time(0, 30), time(2)
        user.telegram_morning_digest_timezone = zone
        user.telegram_morning_digest_enabled = True
        user.telegram_morning_digest_time = time(0, 15)
        set_preferences(db, user, enabled=True, lead=15)
        db.commit()
        local = datetime.combine(DAY, time(0, 45), ZoneInfo(zone))
        instant = local.astimezone(UTC)
        assert instant.date() != DAY
        for message in (
            build_now_message(db, user, now_utc=instant),
            build_today_summary(db, user, now_utc=instant),
        ):
            assert 'Замена 1' in message and 'Старая пара' not in message
            assert '00:30–02:00' in message and '777' in message
        due = (local - timedelta(minutes=30)).astimezone(UTC)
        sent = []
        assert process_due_digests(db, now_utc=due, send_message=sent.append) == 1
        assert '📅 Пар: <b>1</b>' in sent[0].text
        assert 'Замена 1' in sent[0].text and '00:30–02:00' in sent[0].text
        assert 'Старая пара' not in sent[0].text
        sent.clear()
        assert process_class_reminders(db, now_utc=due, send_message=sent.append) == 1
        assert 'Замена 1' in sent[0].text and '00:30–02:00' in sent[0].text
        assert process_class_reminders(db, now_utc=due, send_message=sent.append) == 0


def test_deleted_replacement_does_not_send_class_reminder(harness):
    with harness.SessionLocal() as db:
        user, (replacement,) = replacement_day(db, harness)
        set_preferences(db, user, enabled=True, lead=15)
        db.delete(replacement)
        db.commit()
        assert process_class_reminders(
            db, now_utc=datetime(2026, 9, 29, 7, 45, tzinfo=UTC),
            send_message=lambda _: pytest.fail('Cancelled class must not be sent'),
        ) == 0


def test_morning_digest_counts_multiple_replacements_and_missing_time(harness):
    with harness.SessionLocal() as db:
        user, replacements = replacement_day(db, harness, 3)
        replacements[0].start_time = replacements[0].end_time = None
        db.commit()
        text = build_morning_digest_message(db, user, target_date=DAY, current_local_time=time(8))
        assert '📅 Пар: <b>3</b>' in text
        assert 'Замена 2' in text and '13:00–14:30' in text
        assert '00:00' not in text and 'Старая пара' not in text


def test_tomorrow_and_week_accept_calendar_lesson_events(harness):
    with harness.SessionLocal() as db:
        user, _ = replacement_day(db, harness)
        with patch('app.services.telegram_bot.current_date', return_value=DAY - timedelta(days=1)):
            tomorrow = build_tomorrow_message(db, user)
            week = build_week_message(db, user)
        assert 'Замена 1' in tomorrow and '11:00–12:30' in tomorrow
        assert tomorrow.count('Замена 1') == 1
        assert 'Старая пара' not in tomorrow
        assert '29 сентября — 1 пара' in week
