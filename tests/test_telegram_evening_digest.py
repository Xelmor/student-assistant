"""Evening digest: real DB/calendar, deterministic clocks and mocked Telegram I/O."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
import subprocess
import sys
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from app.models import AcademicEvent, Task, TelegramState, User
from app.services import telegram_evening_digest as evening
from app.services.task_completion import complete_task
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, clear_telegram_link, handle_telegram_update
from app.services.telegram_digest import digest_local_datetime
from telegram_bot import scheduler
from test_telegram_now import DAY, add_lesson, harness

NOW = datetime(2026, 9, 29, 18, tzinfo=UTC)  # Tuesday 21:00 Moscow
TOMORROW = DAY + timedelta(days=1)


def owner(db, harness):
    return db.get(User, harness.first_user_id)


def task(db, harness, title='Задача', **kwargs):
    result = Task(user_id=harness.first_user_id, title=title, **kwargs)
    db.add(result)
    db.commit()
    return result


def render(db, harness, now=NOW):
    return evening.build_evening_digest_message(db, owner(db, harness), now_utc=now)


def enable(harness, hour=21):
    with harness.SessionLocal() as db:
        evening.set_preferences(db, owner(db, harness), enabled=True, hour=hour)
        db.commit()


def tick(harness, now=NOW, sender=None):
    with harness.SessionLocal() as db:
        return scheduler.process_evening_digests(db, now_utc=now, send_message=sender if sender is not None else lambda _: None)


def callback(harness, action, **kwargs):
    with harness.SessionLocal() as db, patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW)):
        return handle_telegram_update(db, harness._callback(action, **kwargs))


def test_busy_day_exact_compact_summary(harness):
    with harness.SessionLocal() as db:
        for i in range(3):
            task(db, harness, f'Готово {i}', is_completed=True, completed_at=datetime(2026, 9, 29, 12+i))
        task(db, harness, 'Отчёт', deadline=datetime(2026, 9, 29, 18))
        task(db, harness, 'Практика по БД', deadline=datetime(2026, 9, 30, 18), priority='high')
        for name, start, end in [('Базы данных', '10:00', '11:30'), ('Физика', '12:00', '13:30'), ('Английский', '14:00', '15:30')]:
            add_lesson(db, harness, name, start, end, day=TOMORROW)
        assert render(db, harness) == (
            '🌙 <b>Итоги дня</b>\n\n✅ Выполнено сегодня: 3\n📌 Осталось активных: 2\n⚠️ Просрочено: 1\n\n'
            '━━━━━━━━━━━━━━\n\n📆 <b>Завтра</b>\n🎓 3 занятия\nПервая пара: Базы данных · 10:00\n📌 1 задача с дедлайном\n\n'
            '━━━━━━━━━━━━━━\n\n🔴 <b>Не забудь</b>\n🔴 Отчёт · до 18:00 · просрочено')


def test_completely_empty_day_has_no_zero_lines(harness):
    with harness.SessionLocal() as db:
        message = render(db, harness)
    assert message == ('🌙 <b>Итоги дня</b>\n\nНа сегодня всё ✅\n\n━━━━━━━━━━━━━━\n\n'
                       '📆 <b>Завтра</b>\n🌿 Завтра без занятий\n📌 Срочных задач нет')
    assert '0' not in message and 'Не забудь' not in message


def test_completed_only_has_no_empty_task_counters(harness):
    with harness.SessionLocal() as db:
        task(db, harness, is_completed=True, completed_at=datetime(2026, 9, 29, 20))
        message = render(db, harness)
    assert 'Выполнено сегодня: 1' in message
    assert 'Осталось' not in message and 'Просрочено' not in message and 'Не забудь' not in message


def test_unknown_completion_timestamp_is_not_inferred_from_creation_or_deadline(harness):
    with harness.SessionLocal() as db:
        task(db, harness, is_completed=True, completed_at=None, created_at=datetime(2026, 9, 29, 12), deadline=datetime(2026, 9, 29, 18))
        assert 'Выполнено' not in render(db, harness)


def test_completion_uses_project_zone_and_user_local_day(harness):
    with harness.SessionLocal() as db:
        user = owner(db, harness)
        user.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        db.commit()
        # At 21:00 Vladivostok, local midnight was 17:00 the previous project day.
        for stamp, completed in [(datetime(2026, 9, 28, 16, 59, 59), True),
                                 (datetime(2026, 9, 28, 17), True),
                                 (datetime(2026, 9, 29, 13), True),
                                 (datetime(2026, 9, 29, 14, 0, 1), True),
                                 (datetime(2026, 9, 29, 12), False)]:
            task(db, harness, is_completed=completed, completed_at=stamp)
        with patch.object(evening, 'APP_ZONE', ZoneInfo('Europe/Moscow')):
            summary = evening.collect_summary(db, user, now_utc=datetime(2026, 9, 29, 11, tzinfo=UTC))
        assert summary.completed == 2 and summary.active == 1


def test_completion_midnight_boundary_and_next_day(harness):
    with harness.SessionLocal() as db:
        task(db, harness, is_completed=True, completed_at=datetime(2026, 9, 29, 23, 59, 59))
        task(db, harness, is_completed=True, completed_at=datetime(2026, 9, 30, 0))
        task(db, harness, deadline=datetime(2026, 10, 1, 18))
        assert 'Выполнено сегодня: 1' in render(db, harness, datetime(2026, 9, 29, 21, tzinfo=UTC))
        assert '1 задача с дедлайном' in render(db, harness, datetime(2026, 9, 29, 21, tzinfo=UTC))


def test_real_completion_and_restore_are_reflected(harness):
    with harness.SessionLocal() as db:
        item = task(db, harness)
        with patch('app.services.task_completion.current_time', return_value=datetime(2026, 9, 29, 20)):
            complete_task(db, item)
        db.commit()
        assert evening.collect_summary(db, owner(db, harness), now_utc=NOW).completed == 1
        item.is_completed, item.completed_at = False, None
        db.commit()
        summary = evening.collect_summary(db, owner(db, harness), now_utc=NOW)
        assert summary.completed == 0 and summary.active == 1


def test_real_website_completion_uses_same_timestamp(harness):
    harness._login()
    with harness.SessionLocal() as db:
        item_id = task(db, harness).id
    csrf = harness._csrf(harness.client.get('/tasks').text)
    with patch('app.services.task_completion.current_time', return_value=datetime(2026, 9, 29, 20)):
        response = harness.client.post(f'/tasks/toggle/{item_id}', data={'csrf_token': csrf}, follow_redirects=False)
    assert response.status_code == 302
    with harness.SessionLocal() as db:
        assert 'Выполнено сегодня: 1' in render(db, harness)


def test_overdue_requires_deadline_and_uses_shared_boundary(harness):
    with harness.SessionLocal() as db:
        task(db, harness, deadline=datetime(2026, 9, 29, 21))
        task(db, harness, scheduled_for_date=DAY - timedelta(days=1))
        task(db, harness, is_completed=True, deadline=datetime(2026, 9, 28, 18))
        summary = evening.collect_summary(db, owner(db, harness), now_utc=NOW)
        assert summary.active == 2 and summary.overdue == 0


def test_tomorrow_deadlines_exclude_completed_and_scheduled_only(harness):
    with harness.SessionLocal() as db:
        task(db, harness, deadline=datetime(2026, 9, 30, 0))
        task(db, harness, deadline=datetime(2026, 9, 30, 23, 59))
        task(db, harness, deadline=datetime(2026, 10, 1, 0))
        task(db, harness, deadline=datetime(2026, 9, 30, 18), is_completed=True)
        task(db, harness, scheduled_for_date=TOMORROW)
        assert evening.collect_summary(db, owner(db, harness), now_utc=NOW).tomorrow_deadlines == 2


@pytest.mark.parametrize('group', ['overdue', 'tomorrow', 'high', 'nearest', 'none'])
def test_one_important_task_in_requested_priority_order(harness, group):
    with harness.SessionLocal() as db:
        expected = None
        if group == 'overdue':
            expected = task(db, harness, 'Просроченная', deadline=datetime(2026, 9, 28, 18))
        if group in {'overdue', 'tomorrow'}:
            item = task(db, harness, 'Завтрашняя', deadline=datetime(2026, 9, 30, 18))
            expected = expected or item
        if group in {'overdue', 'tomorrow', 'high'}:
            item = task(db, harness, 'Важная', priority='high')
            expected = expected or item
        if group != 'none':
            item = task(db, harness, 'Ближайшая', deadline=datetime(2026, 10, 2, 18))
            expected = expected or item
        task(db, harness, 'Без срочности')
        summary = evening.collect_summary(db, owner(db, harness), now_utc=NOW)
        assert summary.important == expected
        message = evening.render_summary(summary)
        assert message.count('Не забудь') == int(expected is not None)
        if group == 'tomorrow':
            assert 'Завтрашняя · завтра до 18:00' in message


@pytest.mark.parametrize('move', [False, True])
def test_tomorrow_override_cancels_regular_and_uses_moved_lesson(harness, move):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Отменённая пара', day=TOMORROW)
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Замена', event_type='day_override', event_date=TOMORROW))
        if move:
            db.add(AcademicEvent(user_id=harness.first_user_id, title='Перенесённая пара', event_type='changed_class', event_date=TOMORROW, start_time=time(11), end_time=time(12, 30)))
        db.commit()
        message = render(db, harness)
        assert 'Отменённая пара' not in message
        assert ('Первая пара: Перенесённая пара · 11:00' in message) == move
        assert ('Завтра без занятий' in message) != move


def test_incomplete_lesson_time_is_not_fabricated(harness):
    with harness.SessionLocal() as db:
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Пара без времени', event_type='changed_class', event_date=TOMORROW))
        db.commit()
        message = render(db, harness)
        assert 'Время занятий указано не полностью' in message
        assert '00:00' not in message


def test_html_escaped_and_summary_bounded(harness):
    with harness.SessionLocal() as db:
        task(db, harness, '<&>' * 50, priority='high')
        add_lesson(db, harness, '<&>' * 33, day=TOMORROW)
        message = render(db, harness)
        assert '&lt;&amp;&gt;' in message and '<&>' not in message and len(message) < 4096


@pytest.mark.parametrize('hour', [19, 20, 21, 22])
def test_selected_time_and_repeated_scheduler_passes(harness, hour):
    enable(harness, hour)
    now = NOW.replace(hour=hour - 3)
    assert tick(harness, now - timedelta(seconds=1)) == 0
    assert tick(harness, now) == 1
    assert tick(harness, now + timedelta(minutes=1)) == 0


def test_default_disabled_and_enable_disable_independent_of_morning(harness):
    with harness.SessionLocal() as db:
        user = owner(db, harness)
        assert evening.preferences(db, user) == {'enabled': False, 'hour': 21}
        user.telegram_morning_digest_enabled = True
        db.commit()
    assert tick(harness) == 0
    assert 'включена' in callback(harness, 'evening_enable').text
    assert 'включена' in callback(harness, 'evening_enable').text
    assert 'выключена' in callback(harness, 'evening_disable').text
    with harness.SessionLocal() as db:
        assert owner(db, harness).telegram_morning_digest_enabled
    assert tick(harness) == 0


def test_settings_persist_are_independent_and_use_existing_buttons(harness):
    assert '🌙 Вечерняя сводка: ❌' in callback(harness, 'settings').text
    assert 'Время: 21:00' in callback(harness, 'evening_settings').text
    callback(harness, 'evening_enable')
    for hour in evening.HOURS:
        reply = callback(harness, f'evening_hour:{hour}')
        assert f'✅ {hour}:00' in str(reply.reply_markup)
        with harness.SessionLocal() as db:
            assert evening.preferences(db, owner(db, harness)) == {'enabled': True, 'hour': hour}
            assert evening.preferences(db, db.get(User, harness.second_user_id)) == {'enabled': False, 'hour': 21}
    assert 'Время: 22:00' in callback(harness, 'evening_hour:99').text
    assert callback(harness, 'evening_time').reply_markup['inline_keyboard'][-1][0]['callback_data'] == 'evening_settings'
    assert callback(harness, 'evening_settings').reply_markup['inline_keyboard'][-1][0]['callback_data'] == 'settings'
    assert len(BOT_COMMANDS) == 6


@pytest.mark.parametrize('delay,expected', [(1, 1), (2, 1), (3, 1), (15, 1), (16, 0)])
def test_scheduler_catchup_window(harness, delay, expected):
    enable(harness)
    assert tick(harness, NOW + timedelta(minutes=delay)) == expected


def test_late_22_hour_digest_does_not_cross_midnight(harness):
    enable(harness, 22)
    assert tick(harness, NOW + timedelta(hours=3)) == 0  # 00:00 next day
    assert tick(harness, NOW + timedelta(days=1, hours=1)) == 1


def test_two_user_timezones_and_host_timezone(harness, monkeypatch):
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    enable(harness)
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        other.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        evening.set_preferences(db, other, enabled=True)
        db.commit()
    sent = []
    assert tick(harness, NOW - timedelta(hours=7), sent.append) == 1
    assert [reply.chat_id for reply in sent] == [8002]
    assert tick(harness, NOW, sent.append) == 1
    assert [reply.chat_id for reply in sent] == [8002, 8001]


def test_two_workers_send_once(harness):
    enable(harness)
    sent = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: tick(harness, sender=sent.append), range(2))) == 1
    assert len(sent) == 1


def test_restart_subprocess_and_next_local_day(harness):
    enable(harness)
    assert tick(harness) == 1
    script = '''
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram_bot.scheduler import process_evening_digests
engine = create_engine(sys.argv[1])
with Session(engine) as db:
    assert process_evening_digests(db, now_utc=datetime(2026,9,29,18,3,tzinfo=UTC), send_message=lambda _: None) == 0
    assert process_evening_digests(db, now_utc=datetime(2026,9,30,18,tzinfo=UTC), send_message=lambda _: None) == 1
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_failure_is_not_sent_and_retry_obeys_backoff(harness):
    enable(harness)
    sender = Mock(side_effect=[TelegramAPIError(category='rate_limit', retry_after=120), None])
    assert tick(harness, sender=sender) == 0
    with harness.SessionLocal() as db:
        row = db.get(TelegramState, f'evening-digest:{harness.first_user_id}:2026-09-29')
        assert not row.data.get('sent') and row.data['attempts'] == 1
    assert tick(harness, NOW + timedelta(minutes=1), sender) == 0
    assert tick(harness, NOW + timedelta(minutes=2), sender) == 1
    assert tick(harness, NOW + timedelta(minutes=3), sender) == 0
    assert sender.call_count == 2


def test_unknown_failure_has_bounded_retries(harness):
    enable(harness)
    sender = Mock(side_effect=RuntimeError('transport error'))
    for minute in range(7):
        assert tick(harness, NOW + timedelta(minutes=minute), sender) == 0
    assert sender.call_count == 5


def test_failed_user_does_not_block_other_users(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        other.telegram_morning_digest_timezone = 'Europe/Moscow'
        evening.set_preferences(db, other, enabled=True)
        db.commit()
    sender = Mock(side_effect=[TelegramAPIError(category='blocked'), None])
    assert tick(harness, sender=sender) == 1
    assert tick(harness, NOW + timedelta(minutes=1), sender) == 0
    assert sender.call_count == 2


def test_unlink_cancels_retry_and_preview(harness):
    enable(harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    with harness.SessionLocal() as db:
        clear_telegram_link(owner(db, harness))
        db.commit()
    assert tick(harness, NOW + timedelta(minutes=1)) == 0
    assert 'подключ' in callback(harness, 'evening_preview').text.lower()


def test_preview_real_data_does_not_mark_auto_delivery(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Моя реальная задача', priority='high')
    preview = callback(harness, 'evening_preview')
    assert 'Моя реальная задача' in preview.text
    with harness.SessionLocal() as db:
        assert db.query(TelegramState).filter(TelegramState.key.startswith('evening-digest:')).count() == 0
    enable(harness)
    sent = []
    assert tick(harness, sender=sent.append) == 1
    assert sent[0].text == preview.text
    assert callback(harness, 'evening_preview').text == preview.text
    assert tick(harness) == 0


def test_ownership_and_private_chat_guard(harness):
    with harness.SessionLocal() as db:
        db.add(Task(user_id=harness.second_user_id, title='Чужая тайна', priority='high'))
        db.commit()
    assert 'Чужая тайна' not in callback(harness, 'evening_preview').text
    with harness.SessionLocal() as db:
        update = harness._callback('evening_preview', chat_id=-100)
        update['callback_query']['message']['chat']['type'] = 'supergroup'
        reply = handle_telegram_update(db, update)
        assert 'личный чат' in reply.text and 'Итоги дня' not in reply.text
        assert owner(db, harness).telegram_chat_id == 8001
    assert tick(harness) == 0


def test_negative_group_chat_is_not_a_scheduler_destination(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        owner(db, harness).telegram_chat_id = -100
        db.commit()
    assert tick(harness) == 0


def test_digest_buttons_invoke_existing_tomorrow_tasks_and_notes(harness):
    reply = callback(harness, 'evening_preview')
    actions = [button['callback_data'] for row in reply.reply_markup['inline_keyboard'] for button in row]
    assert actions == ['tomorrow', 'tasks', 'note_start', 'evening_settings']
    assert evening.digest_keyboard()['inline_keyboard'] == reply.reply_markup['inline_keyboard'][:2]
    assert 'Завтра' in callback(harness, actions[0]).text
    assert 'Задачи' in callback(harness, actions[1]).text
    assert 'Новая заметка' in callback(harness, actions[2]).text


def test_existing_scheduler_calls_evening_service(harness):
    with harness.SessionLocal() as db, patch.object(scheduler, 'retry_pending_replies'), patch.object(scheduler, 'process_due_digests'), patch.object(scheduler, 'process_deadline_reminders'), patch.object(scheduler, 'process_class_reminders'), patch.object(scheduler, 'process_evening_digests') as process:
        scheduler.scheduler_tick(db)
        process.assert_called_once_with(db)


def test_changing_hour_after_send_does_not_send_again_same_day(harness):
    enable(harness, 19)
    assert tick(harness, NOW - timedelta(hours=2)) == 1
    callback(harness, 'evening_hour:21')
    assert tick(harness, NOW) == 0


def test_restart_with_pending_failure_retries_fresh_summary(harness):
    enable(harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    with harness.SessionLocal() as db:
        task(db, harness, 'Добавлено после ошибки', priority='high')
    script = '''
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram_bot.scheduler import process_evening_digests
engine = create_engine(sys.argv[1])
sent = []
with Session(engine) as db:
    assert process_evening_digests(db, now_utc=datetime(2026,9,29,18,1,tzinfo=UTC), send_message=sent.append) == 1
assert len(sent) == 1 and 'Добавлено после ошибки' in sent[0].text
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert tick(harness, NOW + timedelta(minutes=2)) == 0


def test_disable_cancels_pending_retry(harness):
    enable(harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    callback(harness, 'evening_disable')
    assert tick(harness, NOW + timedelta(minutes=1)) == 0


def test_real_telegram_completion_is_counted(harness):
    from app.services.telegram_task_views import task_button
    with harness.SessionLocal() as db:
        item = task(db, harness)
        action = task_button(db, item, 'Готово', 'task_done')['callback_data']
        db.commit()
    with patch('app.services.task_completion.current_time', return_value=datetime(2026, 9, 29, 20)):
        assert 'Задача выполнена' in callback(harness, action).text
    with harness.SessionLocal() as db:
        assert 'Выполнено сегодня: 1' in render(db, harness)


@pytest.mark.parametrize('local_date', ['2026-09-30', '2026-12-31'])
def test_month_and_year_transition_uses_next_local_day(harness, local_date):
    local = datetime.fromisoformat(local_date + 'T21:00:00').replace(tzinfo=ZoneInfo('Europe/Moscow'))
    tomorrow = local.date() + timedelta(days=1)
    with harness.SessionLocal() as db:
        task(db, harness, 'Завтрашний дедлайн', deadline=datetime.combine(tomorrow, time(18)))
        task(db, harness, 'Сделано вчера', is_completed=True, completed_at=local.replace(tzinfo=None) - timedelta(days=1))
        task(db, harness, 'Сделано сегодня', is_completed=True, completed_at=local.replace(tzinfo=None) - timedelta(hours=1))
        add_lesson(db, harness, 'Первая пара нового периода', day=tomorrow)
        summary = evening.collect_summary(db, owner(db, harness), now_utc=local.astimezone(UTC))
        assert summary.completed == 1 and summary.tomorrow_deadlines == 1
        assert summary.lessons[0]['start'].date() == tomorrow
    enable(harness)
    assert tick(harness, local.astimezone(UTC)) == 1
    assert tick(harness, local.astimezone(UTC) + timedelta(minutes=2)) == 0
    assert tick(harness, (local + timedelta(days=1)).astimezone(UTC)) == 1


@pytest.mark.parametrize('day,hours', [('2026-03-29', 23), ('2026-10-25', 25)])
def test_dst_local_day_completion_bounds_and_evening_delivery(harness, day, hours):
    zone = ZoneInfo('Europe/Berlin')
    start = datetime.fromisoformat(day).replace(tzinfo=zone)
    end = start + timedelta(days=1)
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == hours * 3600
    current = end - timedelta(seconds=1)
    with harness.SessionLocal() as db:
        user = owner(db, harness)
        user.telegram_morning_digest_timezone = zone.key
        db.commit()
        for instant in [start.astimezone(UTC) - timedelta(seconds=1), start.astimezone(UTC),
                        start.astimezone(UTC) + timedelta(hours=2), current.astimezone(UTC), end.astimezone(UTC)]:
            completed = instant.astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
            task(db, harness, is_completed=True, completed_at=completed)
        with patch.object(evening, 'APP_ZONE', ZoneInfo('Europe/Moscow')):
            assert evening.collect_summary(db, user, now_utc=current.astimezone(UTC)).completed == 3
    enable(harness)
    due = start.replace(hour=21).astimezone(UTC)
    assert tick(harness, due - timedelta(seconds=1)) == 0
    assert tick(harness, due + timedelta(minutes=2)) == 1
    assert tick(harness, due + timedelta(minutes=3)) == 0


def test_dst_repeated_hour_counts_both_real_completion_instants(harness):
    zone = ZoneInfo('Europe/Berlin')
    with harness.SessionLocal() as db:
        user = owner(db, harness)
        user.telegram_morning_digest_timezone = zone.key
        db.commit()
        for fold in (0, 1):
            local = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=fold)
            task(db, harness, is_completed=True, completed_at=local.astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None))
        with patch.object(evening, 'APP_ZONE', ZoneInfo('Europe/Moscow')):
            assert evening.collect_summary(db, user, now_utc=datetime(2026, 10, 25, 20, tzinfo=UTC)).completed == 2


def test_settings_time_survives_process_restart(harness):
    enable(harness, 20)
    script = '''
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import User
from app.services.telegram_evening_digest import preferences
from telegram_bot.scheduler import process_evening_digests
engine = create_engine(sys.argv[1])
with Session(engine) as db:
    assert preferences(db, db.get(User, int(sys.argv[2]))) == {'enabled': True, 'hour': 20}
    assert process_evening_digests(db, now_utc=datetime(2026,9,29,17,2,tzinfo=UTC), send_message=lambda _: None) == 1
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), str(harness.first_user_id)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_scheduler_selects_only_enabled_users(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        evening.set_preferences(db, other, enabled=False)
        db.commit()
    original = evening.is_due
    seen = []
    def tracked(db, user, current):
        seen.append(user.id)
        return original(db, user, current)
    with patch.object(evening, 'is_due', side_effect=tracked):
        assert tick(harness) == 1
    assert set(seen) == {harness.first_user_id}


def test_preview_in_afternoon_does_not_suppress_evening(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        preview = evening.handle_settings(db, owner(db, harness), 'evening_preview', now_utc=NOW - timedelta(hours=6))
        assert 'Итоги дня' in preview[0]
        assert preview[1]['inline_keyboard'][-1][0]['callback_data'] == 'evening_settings'
        assert db.query(TelegramState).filter(TelegramState.key.startswith('evening-digest:')).count() == 0
    assert tick(harness) == 1


def test_pending_retry_outside_grace_is_not_delivered(harness):
    enable(harness)
    assert tick(harness, sender=Mock(side_effect=TelegramAPIError(category='network'))) == 0
    assert tick(harness, NOW + timedelta(minutes=16)) == 0


def test_scheduled_high_priority_without_deadline_is_not_labelled_overdue(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Важное без дедлайна', priority='high', scheduled_for_date=DAY - timedelta(days=1))
        message = render(db, harness)
        assert 'высокий приоритет' in message
        assert 'Просрочено' not in message and 'просрочено' not in message
