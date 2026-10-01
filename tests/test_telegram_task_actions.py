from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch

import pytest

from app.models import Task, User, TelegramState, Subject, ScheduleItem, TelegramDeadlineReminderLog
from app.services.telegram_bot import handle_telegram_update, TelegramReply, send_telegram_message
from app.services.telegram_task_views import revision, task_page
from app.services.telegram_digest import digest_local_datetime
from app.services.calendar_service import build_calendar_event_map
from telegram_bot import scheduler
from test_telegram_task_draft import harness, frozen_clock, NOW, text, click, action, count, deliver


@pytest.fixture(autouse=True)
def fixed_mutation_clock():
    with patch('app.services.task_completion.current_time', return_value=datetime(2026, 9, 30, 12)), patch('telegram_bot.scheduler.utcnow', return_value=NOW.replace(tzinfo=None)):
        yield


def task(harness, title='Практика по БД', deadline=datetime(2026, 9, 30, 18, 30), **kwargs):
    with harness.SessionLocal() as db:
        item = Task(user_id=kwargs.pop('user_id', harness.first_user_id), title=title, deadline=deadline,
                    created_at=datetime(2026, 9, 29, 12), **kwargs)
        db.add(item)
        db.commit()
        return item.id


def task_action(reply, kind):
    return next(b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row if b.get('callback_data', '').startswith(kind + ':'))


def press(harness, reply, kind, **kwargs):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._callback(task_action(reply, kind), **kwargs))


def stored(harness, tid):
    with harness.SessionLocal() as db:
        item = db.get(Task, tid)
        return item.deadline, item.is_completed, item.title


def choose(harness, option):
    menu = press(harness, text(harness, '/tasks'), 'task_reschedule')
    return click(harness, menu, 'add_task_reschedule_' + option)


def confirm(harness, preview):
    return click(harness, preview, 'add_task_reschedule_save')


def test_done_restore_and_old_buttons_never_toggle_again(harness):
    tid = task(harness)
    card = text(harness, '/tasks')
    done = press(harness, card, 'task_done')
    assert 'Задача выполнена' in done.text and 'Осталось активных задач: 0' in done.text
    assert stored(harness, tid)[1]
    assert 'Практика по БД' not in text(harness, '/tasks').text
    assert 'неактуальна' in press(harness, card, 'task_done').text
    restored = press(harness, done, 'task_restore')
    assert 'Задача снова активна' in restored.text and not stored(harness, tid)[1]
    assert 'неактуальна' in press(harness, done, 'task_restore').text
    assert 'неактуальна' in press(harness, card, 'task_done').text
    assert not stored(harness, tid)[1] and count(harness) == 1
    press(harness, restored, 'task_done')
    assert stored(harness, tid)[1]


@pytest.mark.parametrize('kind', ['task_done', 'task_restore', 'task_reschedule', 'task_edit'])
def test_foreign_missing_ids_and_unlinked_users_cannot_read_or_mutate(harness, kind):
    foreign = task(harness, title='Чужой секрет', user_id=harness.second_user_id)
    with harness.SessionLocal() as db:
        version = revision(db, db.get(Task, foreign))
        for tid in [foreign, 99999]:
            reply = handle_telegram_update(db, harness._callback(f'{kind}:{tid}:{version}'))
            assert 'неактуальна' in reply.text and 'Чужой секрет' not in reply.text
        reply = handle_telegram_update(db, harness._callback(f'{kind}:{foreign}:{version}', telegram_user_id=9999))
        assert 'Аккаунт не подключён' in reply.text
    assert not stored(harness, foreign)[1]


@pytest.mark.parametrize('kind', ['task_done', 'task_restore', 'task_reschedule', 'task_edit'])
def test_group_does_not_read_modify_or_rebind(harness, kind):
    tid = task(harness)
    with harness.SessionLocal() as db:
        version = revision(db, db.get(Task, tid))
        update = harness._callback(f'{kind}:{tid}:{version}', chat_id=-55)
        update['callback_query']['message']['chat']['type'] = 'supergroup'
        reply = handle_telegram_update(db, update)
        assert reply.text == 'Открой личный чат с ботом.'
        assert db.get(User, harness.first_user_id).telegram_chat_id == 8001
    assert stored(harness, tid)[:2] == (datetime(2026, 9, 30, 18, 30), False)


@pytest.mark.parametrize('deadline,option,expected', [
    (datetime(2026, 9, 30, 18, 30), 'tomorrow', datetime(2026, 10, 1, 18, 30)),
    (None, 'tomorrow', datetime(2026, 10, 1, 23, 59)),
    (datetime(2026, 9, 30, 18, 30), '3', datetime(2026, 10, 3, 18, 30)),
    (datetime(2026, 9, 30, 18, 30), '7', datetime(2026, 10, 7, 18, 30)),
    (None, '3', datetime(2026, 10, 3, 23, 59)),
    (None, '7', datetime(2026, 10, 7, 23, 59)),
    (datetime(2026, 12, 30, 18, 30), '3', datetime(2027, 1, 2, 18, 30)),
    (None, 'today', datetime(2026, 9, 30, 20)),
])
def test_quick_reschedule_preserves_time_and_requires_confirmation(harness, deadline, option, expected):
    tid = task(harness, deadline=deadline)
    preview = choose(harness, option)
    assert 'Новый дедлайн' in preview.text and 'Было:' in preview.text and 'Станет:' in preview.text
    assert stored(harness, tid)[0] == deadline
    reply = confirm(harness, preview)
    assert 'Дедлайн перенесён' in reply.text
    assert stored(harness, tid)[0] == expected
    assert 'неактуальна' in confirm(harness, preview).text.lower()
    assert stored(harness, tid)[0] == expected and count(harness) == 1


@pytest.mark.parametrize('phrase,expected', [
    ('02.10 18:30', datetime(2026, 10, 2, 18, 30)),
    ('завтра 20:00', datetime(2026, 10, 1, 20)),
    ('в пятницу 17:00', datetime(2026, 10, 2, 17)),
])
def test_custom_date_uses_existing_parser(harness, phrase, expected):
    tid = task(harness)
    prompt = choose(harness, 'custom')
    assert 'Введите новую дату' in prompt.text
    preview = text(harness, phrase)
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)
    confirm(harness, preview)
    assert stored(harness, tid)[0] == expected


@pytest.mark.parametrize('phrase', ['29.09.2026', 'сегодня 10:00', '31.02', 'когда-нибудь'])
def test_invalid_or_past_custom_dates_stay_in_dialog(harness, phrase):
    tid = task(harness)
    choose(harness, 'custom')
    reply = text(harness, phrase)
    assert '⚠️' in reply.text
    assert 'add_task_reschedule_save' not in str(reply.reply_markup)
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)


def test_today_20_is_hidden_after_it_passes_in_user_timezone(harness):
    tid = task(harness)
    with harness.SessionLocal() as db:
        db.get(User, harness.first_user_id).telegram_morning_digest_timezone = 'Pacific/Auckland'
        db.commit()  # 22:00 in the user's timezone.
    menu = press(harness, text(harness, '/tasks'), 'task_reschedule')
    assert 'Сегодня, 20:00' not in str(menu.reply_markup)
    # Even a forged option with a valid draft stamp is checked again.
    raw = action(menu, 'add_task_reschedule_tomorrow').replace('_tomorrow', '_today')
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._callback(raw))
    assert 'уже прошла' in reply.text
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)


def test_user_midnight_and_year_transition(harness):
    tid = task(harness, deadline=None)
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW.replace(month=12, day=31, hour=22))):
        preview = choose(harness, 'tomorrow')
        confirm(harness, preview)
    assert stored(harness, tid)[0] == datetime(2027, 1, 2, 23, 59)


@pytest.mark.parametrize('cancel', ['/cancel', 'отмена', 'button'])
def test_cancel_reschedule_keeps_task_and_expires_old_confirmation(harness, cancel):
    tid = task(harness)
    preview = choose(harness, '3')
    click(harness, preview, 'add_task_cancel') if cancel == 'button' else text(harness, cancel)
    assert 'неактуальна' in confirm(harness, preview).text.lower()
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)


def test_back_does_not_write_and_old_step_cannot_confirm(harness):
    tid = task(harness)
    preview = choose(harness, '3')
    back = click(harness, preview, 'add_task_reschedule_back')
    assert 'На когда?' in back.text
    assert 'неактуальна' in confirm(harness, preview).text.lower()
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)


def test_expired_dialog_and_deleted_task_are_safe(harness):
    tid = task(harness)
    preview = choose(harness, '3')
    with harness.SessionLocal() as db:
        db.get(TelegramState, 'dialog:7001').expires_at = NOW.replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    assert 'неактуальна' in confirm(harness, preview).text.lower()
    preview = choose(harness, '3')
    with harness.SessionLocal() as db:
        db.delete(db.get(Task, tid)); db.commit()
    assert 'неактуальна' in confirm(harness, preview).text
    assert count(harness) == 0


def test_external_changes_invalidate_card_and_pending_reschedule(harness):
    tid = task(harness)
    card = text(harness, '/tasks')
    menu = press(harness, card, 'task_reschedule')
    preview = click(harness, menu, 'add_task_reschedule_3')
    with harness.SessionLocal() as db:
        db.get(Task, tid).deadline = datetime(2026, 10, 9, 12)
        db.commit()
    assert 'неактуальна' in confirm(harness, preview).text
    assert 'неактуальна' in press(harness, card, 'task_done').text
    assert stored(harness, tid)[0] == datetime(2026, 10, 9, 12)


def test_edit_updates_existing_record_and_preserves_unedited_fields(harness):
    tid = task(harness, title='Старое название', description='Сохранить описание', difficulty='hard')
    step = press(harness, text(harness, '/tasks'), 'task_edit')
    assert 'Сейчас: Старое название' in step.text
    step = text(harness, 'Новое название')
    step = click(harness, step, 'add_task_deadline_tomorrow')
    step = click(harness, step, 'add_task_keep')
    step = click(harness, step, 'add_task_priority_high')
    assert 'Сохранить изменения?' in step.text
    assert stored(harness, tid)[2] == 'Старое название'
    reply = click(harness, step, 'add_task_quick_create')
    assert 'Задача изменена' in reply.text and count(harness) == 1
    with harness.SessionLocal() as db:
        item = db.get(Task, tid)
        assert (item.title, item.deadline, item.priority, item.description, item.difficulty) == ('Новое название', datetime(2026, 10, 1, 23, 59), 'high', 'Сохранить описание', 'hard')


@pytest.mark.parametrize('change', ['owner', 'deleted', 'completed', 'deadline'])
def test_edit_rechecks_ownership_and_revision_before_save(harness, change):
    tid = task(harness)
    step = press(harness, text(harness, '/tasks'), 'task_edit')
    for _ in range(4):
        step = click(harness, step, 'add_task_keep')
    with harness.SessionLocal() as db:
        item = db.get(Task, tid)
        if change == 'owner': item.user_id = harness.second_user_id
        elif change == 'deleted': db.delete(item)
        elif change == 'completed': item.is_completed = True
        else: item.deadline = datetime(2026, 10, 9, 12)
        db.commit()
    assert 'неактуальна' in click(harness, step, 'add_task_quick_create').text
    assert count(harness) == (0 if change == 'deleted' else 1)


def test_edit_can_keep_existing_overdue_deadline(harness):
    tid = task(harness, deadline=datetime(2026, 9, 29, 18))
    step = press(harness, text(harness, '/tasks'), 'task_edit')
    step = text(harness, 'Уточнённое название')
    for _ in range(3): step = click(harness, step, 'add_task_keep')
    click(harness, step, 'add_task_quick_create')
    assert stored(harness, tid) == (datetime(2026, 9, 29, 18), False, 'Уточнённое название')


def test_pagination_sorting_and_visible_done_snapshot(harness):
    values = [
        ('Без даты', None, 'medium'), ('Ближайший', datetime(2026, 10, 1, 12), 'medium'),
        ('Высокий', None, 'high'), ('Сегодняшний', datetime(2026, 9, 30, 18), 'medium'),
        ('Просроченный', datetime(2026, 9, 29, 18), 'low'),
    ]
    for title, deadline, priority in values: task(harness, title, deadline, priority=priority)
    task(harness, 'Готовая', is_completed=True)
    reply = text(harness, '/tasks')
    assert 'Активных: 5' in reply.text and 'На сегодня: 1' in reply.text and 'Просрочено: 1' in reply.text
    for index, title in enumerate(['Просроченный', 'Сегодняшний', 'Высокий', 'Ближайший', 'Без даты']):
        assert f'<b>{title}</b>' in reply.text and 'Готовая' not in reply.text
        assert len(reply.reply_markup['inline_keyboard']) <= 4
        if index < 4: reply = click(harness, reply, f'tasks_page:{index + 1}')
    assert 'Вперёд' not in str(reply.reply_markup)
    text(harness, '/done 1')
    with harness.SessionLocal() as db:
        assert db.query(Task).filter_by(title='Без даты').one().is_completed


def test_restart_between_reschedule_choice_and_confirmation(harness):
    import json
    import subprocess
    import sys
    tid = task(harness)
    preview = choose(harness, '3')
    update = harness._callback(action(preview, 'add_task_reschedule_save'))
    script = '''
import json, sys
from datetime import datetime, UTC
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.telegram_bot import handle_telegram_update
from app.services.telegram_digest import digest_local_datetime
now = datetime(2026, 9, 30, 9, tzinfo=UTC)
engine = create_engine(sys.argv[1])
with Session(engine) as db, patch('app.services.telegram_bot.utcnow', return_value=now.replace(tzinfo=None)), patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, now)):
    reply = handle_telegram_update(db, json.loads(sys.argv[2]))
    assert 'Дедлайн перенесён' in reply.text
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), json.dumps(update)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert stored(harness, tid)[0] == datetime(2026, 10, 3, 18, 30)


def test_duplicate_updates_and_callbacks_reschedule_only_once(harness):
    tid = task(harness)
    preview = choose(harness, '3')
    update = harness._callback(action(preview, 'add_task_reschedule_save'))
    sent = []
    deliver(harness, update, 100, sent.append)
    deliver(harness, update, 100, sent.append)
    deliver(harness, update, 101, sent.append)
    assert len(sent) == 2
    assert 'Дедлайн перенесён' in sent[0].text and 'неактуальна' in sent[1].text.lower()
    assert stored(harness, tid)[0] == datetime(2026, 10, 3, 18, 30)


def test_recurring_task_completion_does_not_duplicate_next_occurrence(harness):
    tid = task(harness, recurrence_type='daily')
    card = text(harness, '/tasks')
    done = press(harness, card, 'task_done')
    press(harness, card, 'task_done')
    assert count(harness) == 2
    active = press(harness, done, 'task_restore')
    press(harness, active, 'task_done')
    assert count(harness) == 2 and stored(harness, tid)[1]


def test_completed_task_is_immediately_visible_on_site(harness):
    tid = task(harness)
    press(harness, text(harness, '/tasks'), 'task_done')
    harness._login()
    response = harness.client.get('/tasks')
    assert response.status_code == 200 and 'Практика по БД' in response.text
    with harness.SessionLocal() as db:
        assert db.get(Task, tid).is_completed


def test_website_deadline_edit_is_visible_in_next_tasks(harness):
    tid = task(harness)
    harness._login()
    csrf = harness._csrf(harness.client.get('/tasks').text)
    response = harness.client.post(f'/tasks/edit/{tid}', data={'csrf_token': csrf, 'title': 'Практика по БД', 'deadline': '2026-10-05T15:30'}, follow_redirects=False)
    assert response.status_code == 302
    assert '5 октября 2026, 15:30' in text(harness, '/tasks').text


def test_reschedule_is_visible_in_today_calendar_and_removes_old_lesson_placement(harness):
    tid = task(harness, deadline=datetime(2026, 10, 5, 12))
    with harness.SessionLocal() as db:
        subject = Subject(user_id=harness.first_user_id, name='Математика')
        db.add(subject); db.flush()
        lesson = ScheduleItem(user_id=harness.first_user_id, subject_id=subject.id, weekday=0, start_time=time(10), end_time=time(11))
        db.add(lesson); db.flush()
        item = db.get(Task, tid)
        item.scheduled_for_date, item.schedule_item_id, item.subject_id = datetime(2026, 10, 5).date(), lesson.id, subject.id
        db.commit()
    confirm(harness, choose(harness, 'today'))
    assert 'до 20:00' in text(harness, '/today').text
    with harness.SessionLocal() as db:
        item = db.get(Task, tid)
        assert item.scheduled_for_date is None and item.schedule_item_id is None and item.subject_id is not None
        events = build_calendar_event_map(db.get(User, harness.first_user_id), db, 2026, 9)['event_map']
        assert any(e['task_id'] == tid and e['start'] == datetime(2026, 9, 30, 20) for e in events[NOW.date()])
        assert not any(e['task_id'] == tid for e in events.get(datetime(2026, 10, 5).date(), []))


def notifications(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_deadline_reminders_enabled = True
        user.telegram_deadline_reminder_hours = 2
        db.commit()


def tick(harness, sender, instant=NOW):
    with harness.SessionLocal() as db:
        return scheduler.process_deadline_reminders(db, now_utc=instant, send_message=sender)


def test_completed_task_has_no_reminder_and_restore_allows_future_reminder(harness):
    tid = task(harness, deadline=datetime(2026, 9, 30, 13))
    notifications(harness)
    done = press(harness, text(harness, '/tasks'), 'task_done')
    sender = Mock()
    assert tick(harness, sender) == 0
    press(harness, done, 'task_restore')
    assert tick(harness, sender) == 1
    assert tick(harness, sender) == 0
    assert sender.call_count == 1


def test_failed_old_reminder_is_not_retried_after_reschedule(harness):
    from app.services.telegram_bot import TelegramAPIError
    tid = task(harness, deadline=datetime(2026, 9, 30, 13))
    notifications(harness)
    failed = Mock(side_effect=TelegramAPIError(category='network'))
    assert tick(harness, failed) == 0
    assert failed.call_count == 1
    confirm(harness, choose(harness, 'tomorrow'))
    sent = Mock()
    assert tick(harness, sent) == 0
    assert tick(harness, sent, NOW + timedelta(days=1)) == 1
    assert '1 октября' not in sent.call_args.args[0].text  # Reminder uses numeric dates.
    assert '01.10.2026 в 13:00' in sent.call_args.args[0].text
    assert tick(harness, sent, NOW + timedelta(days=1)) == 0
    assert sent.call_count == 1


def test_sent_old_deadline_log_does_not_suppress_new_deadline(harness):
    tid = task(harness, deadline=datetime(2026, 9, 30, 13))
    notifications(harness)
    sender = Mock()
    assert tick(harness, sender) == 1
    confirm(harness, choose(harness, 'tomorrow'))
    assert tick(harness, sender, NOW + timedelta(days=1)) == 1
    with harness.SessionLocal() as db:
        logs = db.query(TelegramDeadlineReminderLog).filter_by(task_id=tid).all()
        assert len(logs) == 2 and len({log.reminder_date_key for log in logs}) == 2


def test_scheduler_uses_user_local_deadline_and_offers_task_actions(harness):
    tid = task(harness, deadline=datetime(2026, 9, 30, 20))
    notifications(harness)
    with harness.SessionLocal() as db:
        db.get(User, harness.first_user_id).telegram_morning_digest_timezone = 'Asia/Vladivostok'
        db.commit()  # 19:00 user-local now.
    sender = Mock()
    assert tick(harness, sender) == 1
    reply = sender.call_args.args[0]
    assert '30.09.2026 в 20:00 (Asia/Vladivostok)' in reply.text
    assert task_action(reply, 'task_reschedule').startswith(f'task_reschedule:{tid}:')
    assert 'На когда?' in press(harness, reply, 'task_reschedule').text


def test_callback_acknowledged_before_message_delivery(harness):
    task(harness)
    reply = press(harness, text(harness, '/tasks'), 'task_done')
    with patch('app.services.telegram_bot.call_telegram_api', return_value={}) as api:
        send_telegram_message(reply)
    assert api.call_args_list[0].args[0] == 'answerCallbackQuery'
    assert api.call_args_list[0].args[1]['callback_query_id'] == reply.callback_query_id


def test_previous_confirmation_cannot_save_a_new_choice(harness):
    tid = task(harness)
    first = choose(harness, '3')
    back = click(harness, first, 'add_task_reschedule_back')
    second = click(harness, back, 'add_task_reschedule_7')
    assert 'неактуальна' in confirm(harness, first).text
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)
    confirm(harness, second)
    assert stored(harness, tid)[0] == datetime(2026, 10, 7, 18, 30)


def test_edit_cannot_remove_required_recurring_deadline(harness):
    tid = task(harness, recurrence_type='daily')
    step = press(harness, text(harness, '/tasks'), 'task_edit')
    step = click(harness, step, 'add_task_keep')
    step = click(harness, step, 'add_task_deadline_none')
    step = click(harness, step, 'add_task_keep')
    step = click(harness, step, 'add_task_keep')
    reply = click(harness, step, 'add_task_quick_create')
    assert 'Для повторяющейся задачи нужно указать дедлайн' in reply.text
    assert stored(harness, tid)[0] == datetime(2026, 9, 30, 18, 30)
    assert count(harness) == 1
