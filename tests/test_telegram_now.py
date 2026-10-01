from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import test_telegram_bot as harness_module
from app.core.config import settings
from app.models import AcademicEvent, ScheduleItem, Subject, User
from app.services.telegram_bot import BOT_COMMANDS, handle_telegram_update
from app.services.telegram_now import build_now_message, format_interval


DAY = date(2026, 9, 29)
MOSCOW = ZoneInfo('Europe/Moscow')


@pytest.fixture
def harness():
    case = harness_module.TelegramBotTests()
    case._testMethodName = 'now'
    case.setUp()
    with case.SessionLocal() as db:
        user = db.get(User, case.first_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7001, 8001
        user.telegram_morning_digest_timezone = 'Europe/Moscow'
        db.commit()
    with patch('app.services.calendar_service.current_time', return_value=datetime(2026, 9, 29, 10)):
        yield case
    case.tearDown()


def add_lesson(db, harness, title='Математика', start='09:00', end='10:30', room='301', day=DAY, user_id=None):
    owner = user_id or harness.first_user_id
    subject = Subject(user_id=owner, name=title)
    db.add(subject)
    db.flush()
    item = ScheduleItem(user_id=owner, subject_id=subject.id, weekday=day.weekday(),
                        start_time=time.fromisoformat(start), end_time=time.fromisoformat(end), room=room)
    db.add(item)
    db.commit()
    return item


def render(db, harness, local='2026-09-29T09:20:00'):
    instant = datetime.fromisoformat(local).replace(tzinfo=MOSCOW).astimezone(UTC)
    return build_now_message(db, db.get(User, harness.first_user_id), now_utc=instant)


def two_lessons(db, harness):
    add_lesson(db, harness)
    add_lesson(db, harness, 'Физика', '11:30', '13:00', '205')


def test_current_lesson_and_time_until_next(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        assert render(db, harness) == (
            '📍 <b>Сейчас</b>\n\n🎓 <b>Математика</b>\n09:00–10:30 · Ауд. 301\n\n'
            'До конца: 1 ч 10 мин\n\nДальше:\n🎓 <b>Физика</b>\n11:30 · Ауд. 205\nЧерез 2 ч 10 мин'
        )


def test_before_first_lesson(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        assert render(db, harness, '2026-09-29T08:13:00') == (
            '📍 Учебный день ещё не начался\n\nПервая пара:\n'
            '🎓 <b>Математика</b>\n09:00–10:30 · Ауд. 301\n\nЧерез 47 мин'
        )


def test_gap_between_lessons(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        assert render(db, harness, '2026-09-29T10:43:00') == (
            '📍 Свободное окно\n\nСледующая пара:\n'
            '🎓 <b>Физика</b>\n11:30–13:00 · Ауд. 205\n\nЧерез 47 мин'
        )


@pytest.mark.parametrize('clock,expected', [
    ('08:59:59', 'Учебный день ещё не начался'),
    ('09:00:00', '📍 <b>Сейчас</b>'),
    ('10:29:59', 'До конца: 1 мин'),
    ('10:30:00', 'Свободное окно'),
    ('11:30:00', '📍 <b>Сейчас</b>'),
    ('13:00:00', 'На сегодня занятия закончились'),
])
def test_start_inclusive_end_exclusive(harness, clock, expected):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        message = render(db, harness, f'2026-09-29T{clock}')
        assert expected in message
        assert 'До конца: 0 мин' not in message
        if clock == '11:30:00':
            assert 'Математика' not in message
            assert 'Это последняя пара на сегодня.' in message


def test_adjacent_lessons_switch_exactly_at_boundary(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        add_lesson(db, harness, 'Физика', '10:30', '12:00')
        message = render(db, harness, '2026-09-29T10:30:00')
        assert '📍 <b>Сейчас</b>' in message
        assert 'Физика' in message
        assert 'Математика' not in message
        assert 'До конца: 1 ч 30 мин' in message


def test_finished_today_shows_first_lesson_tomorrow(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        add_lesson(db, harness, 'Английский', '09:00', '10:30', '102', DAY + timedelta(days=1))
        assert render(db, harness, '2026-09-29T15:00:00') == (
            '✅ На сегодня занятия закончились.\n\nСледующая пара завтра:\n'
            '🎓 <b>Английский</b>\n09:00–10:30 · Ауд. 102'
        )


def test_finished_today_and_tomorrow_empty(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        assert render(db, harness, '2026-09-29T10:30:00') == (
            '✅ На сегодня занятия закончились.\n\nНа завтра занятий нет.'
        )


def test_empty_today_searches_next_study_day(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'История', '10:00', '11:30', '401', DAY + timedelta(days=2))
        assert render(db, harness) == (
            '🌿 Сегодня занятий нет.\n\nБлижайшая пара — 01.10:\n'
            '🎓 <b>История</b>\n10:00–11:30 · Ауд. 401'
        )


def test_empty_today_uses_tomorrow_label(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, day=DAY + timedelta(days=1))
        assert 'Следующая пара завтра:' in render(db, harness)


@pytest.mark.parametrize('offset,found', [(7, True), (8, False)])
def test_search_is_bounded_to_seven_days(harness, offset, found):
    with harness.SessionLocal() as db:
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Разовая пара', event_type='changed_class',
                             event_date=DAY + timedelta(days=offset), start_time=time(9), end_time=time(10)))
        db.commit()
        message = render(db, harness)
        assert ('Разовая пара' in message) is found
        if not found:
            assert 'В ближайшие 7 дней занятий нет.' in message


def test_empty_week(harness):
    with harness.SessionLocal() as db:
        assert render(db, harness) == '🌿 Сегодня занятий нет.\n\nВ ближайшие 7 дней занятий нет.'


def test_midnight_changes_day_and_handles_month_boundary(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Среда', '20:00', '21:00', day=date(2026, 9, 30))
        add_lesson(db, harness, 'Четверг', '00:00', '01:30', day=date(2026, 10, 1))
        before = render(db, harness, '2026-09-30T23:59:59')
        after = render(db, harness, '2026-10-01T00:00:00')
        assert 'На сегодня занятия закончились' in before
        assert 'Следующая пара завтра:' in before
        assert '📍 <b>Сейчас</b>' in after
        assert 'Четверг' in after and 'Среда' not in after
        assert 'До конца: 1 ч 30 мин' in after


@pytest.mark.parametrize('room', [None, '', '  '])
def test_missing_room_does_not_render_empty_label(harness, room):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, room=room)
        message = render(db, harness)
        assert '09:00–10:30' in message
        assert 'Ауд.' not in message
        assert ' · ' not in message


def test_html_in_title_and_room_is_escaped(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, title='Математика <&>', room='<301&>')
        message = render(db, harness)
        assert 'Математика &lt;&amp;&gt;' in message
        assert 'Ауд. &lt;301&amp;&gt;' in message


def test_user_timezone_is_used_instead_of_server_day(harness, monkeypatch):
    monkeypatch.setenv('TZ', 'UTC')
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        add_lesson(db, harness)
        # Monday 23:20 UTC is Tuesday 09:20 at the user's location.
        message = build_now_message(db, user, now_utc=datetime(2026, 9, 28, 23, 20, tzinfo=UTC))
        assert '📍 <b>Сейчас</b>' in message
        assert 'До конца: 1 ч 10 мин' in message


def test_missing_user_timezone_falls_back_to_project(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_timezone = None
        add_lesson(db, harness)
        with patch('app.services.telegram_digest.settings', replace(settings, timezone='Asia/Novosibirsk')):
            message = build_now_message(db, user, now_utc=datetime(2026, 9, 29, 2, 20, tzinfo=UTC))
        assert 'До конца: 1 ч 10 мин' in message


def test_cancelled_day_uses_calendar_replacement(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Отменённая математика')
        db.add_all([
            AcademicEvent(user_id=harness.first_user_id, title='Особый день', event_type='day_override', event_date=DAY),
            AcademicEvent(user_id=harness.first_user_id, title='Перенесённая физика', event_type='changed_class',
                          event_date=DAY, start_time=time(10, 15), end_time=time(11, 45), room='205'),
        ])
        db.commit()
        message = render(db, harness, '2026-09-29T10:30:00')
        assert 'Перенесённая физика' in message
        assert 'Отменённая математика' not in message
        assert 'До конца: 1 ч 15 мин' in message


def test_cancelled_lesson_moved_to_another_day(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Старая пара')
        db.add_all([
            AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY),
            AcademicEvent(user_id=harness.first_user_id, title='Новая пара', event_type='changed_class',
                          event_date=DAY + timedelta(days=1), start_time=time(11), end_time=time(12, 30)),
        ])
        db.commit()
        message = render(db, harness)
        assert message.startswith('🌿 Сегодня занятий нет.')
        assert 'Следующая пара завтра:' in message
        assert 'Новая пара' in message
        assert 'Старая пара' not in message


def test_tomorrow_cancellation_is_respected(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        add_lesson(db, harness, day=DAY + timedelta(days=1))
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY + timedelta(days=1)))
        db.commit()
        assert 'На завтра занятий нет.' in render(db, harness, '2026-09-29T15:00:00')


def test_summer_schedule_obeys_calendar_rules(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, day=date(2026, 7, 1))
        assert render(db, harness, '2026-07-01T09:20:00').startswith('🌿 Сегодня занятий нет.')


@pytest.mark.parametrize('start,end', [(None, None), (time(9), None), (None, time(10))])
def test_one_off_lesson_without_complete_time_does_not_invent_status(harness, start, end):
    with harness.SessionLocal() as db:
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Без времени', event_type='changed_class',
                             event_date=DAY, start_time=start, end_time=end))
        db.commit()
        message = render(db, harness)
        assert 'без полного времени' in message
        assert 'До конца:' not in message
        assert 'занятия закончились' not in message


def test_now_callback_and_refresh_recalculate_current_time(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        with patch('app.services.telegram_now.digest_local_datetime', return_value=datetime(2026, 9, 29, 10, 20, tzinfo=MOSCOW)):
            reply = handle_telegram_update(db, harness._callback('now'))
        assert reply.callback_query_id == 'callback-now'
        assert 'До конца: 10 мин' in reply.text
        assert reply.reply_markup == {'inline_keyboard': [
            [{'text': '📅 Сегодня', 'callback_data': 'today'}, {'text': '📌 Задачи', 'callback_data': 'tasks'}],
            [{'text': '🔄 Обновить', 'callback_data': 'now'}],
        ]}
        refresh_action = reply.reply_markup['inline_keyboard'][1][0]['callback_data']
        with patch('app.services.telegram_now.digest_local_datetime', return_value=datetime(2026, 9, 29, 10, 30, tzinfo=MOSCOW)):
            refreshed = handle_telegram_update(db, harness._callback(refresh_action))
        assert 'Свободное окно' in refreshed.text
        assert 'Через 1 ч' in refreshed.text
        assert refreshed.reply_markup == reply.reply_markup


def test_main_menu_now_is_first_and_command_menu_stays_six(harness):
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._update('/start'))
        assert reply.reply_markup['inline_keyboard'][0] == [{'text': '📍 Сейчас', 'callback_data': 'now'}]
    assert len(BOT_COMMANDS) == 6
    assert 'now' not in [item['command'] for item in BOT_COMMANDS]


def test_unlinked_now_does_not_query_schedule(harness):
    with harness.SessionLocal() as db:
        with patch('app.services.telegram_bot.build_now_message') as builder:
            reply = handle_telegram_update(db, harness._callback('now', telegram_user_id=9999))
        builder.assert_not_called()
        assert 'Аккаунт не подключён' in reply.text
        assert reply.callback_query_id == 'callback-now'


@pytest.mark.parametrize('kind', ['callback', 'command'])
def test_group_cannot_receive_schedule_or_change_private_chat(harness, kind):
    update = harness._callback('now', chat_id=-55) if kind == 'callback' else harness._update('/now', chat_id=-55)
    message = update['callback_query']['message'] if kind == 'callback' else update['message']
    message['chat']['type'] = 'supergroup'
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        with patch('app.services.telegram_bot.build_now_message') as builder:
            reply = handle_telegram_update(db, update)
        builder.assert_not_called()
        assert reply.text == 'Открой личный чат с ботом.'
        assert db.get(User, harness.first_user_id).telegram_chat_id == 8001


def test_other_users_schedule_and_cancellations_do_not_leak(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        add_lesson(db, harness, 'Чужая пара', user_id=harness.second_user_id)
        db.add(AcademicEvent(user_id=harness.second_user_id, title='Чужая отмена', event_type='day_override', event_date=DAY))
        db.commit()
        message = render(db, harness)
        assert 'Математика' in message
        assert 'Чужая' not in message


@pytest.mark.parametrize('seconds,label', [
    (300, '5 мин'), (2820, '47 мин'), (4200, '1 ч 10 мин'), (7200, '2 ч'),
    (3660, '1 ч 1 мин'), (1, '1 мин'), (59, '1 мин'), (60, '1 мин'), (0, '0 мин'), (-1, '0 мин'),
])
def test_human_interval(seconds, label):
    assert format_interval(timedelta(seconds=seconds)) == label
