from datetime import UTC, datetime, timedelta
import json
import os
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from app.models import Subject, Task, TelegramState, TelegramUpdate, User
from app.services import telegram_bot
from app.services.calendar_service import build_calendar_event_map
from app.services.telegram_bot import TelegramAPIError, handle_telegram_update
from app.services.telegram_delivery import process_update
from app.services.telegram_digest import digest_local_datetime
from test_telegram_now import harness

NOW = datetime(2026, 9, 30, 9, tzinfo=UTC)  # 12:00 Moscow


@pytest.fixture(autouse=True)
def frozen_clock():
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW)), patch('app.services.telegram_bot.utcnow', return_value=NOW.replace(tzinfo=None)), patch('app.services.telegram_state.utcnow', return_value=NOW.replace(tzinfo=None)), patch('app.services.telegram_delivery.utcnow', return_value=NOW.replace(tzinfo=None)):
        yield


def text(harness, message, **kwargs):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._update(message, **kwargs))


def action(reply, prefix):
    return next(button['callback_data'] for row in reply.reply_markup['inline_keyboard'] for button in row if button.get('callback_data', '').split('|')[0] == prefix)


def click(harness, reply, prefix, **kwargs):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._callback(action(reply, prefix), **kwargs))


def subjects(harness, *names, owner=None):
    with harness.SessionLocal() as db:
        values = [Subject(user_id=owner or harness.first_user_id, name=name) for name in names]
        db.add_all(values)
        db.commit()
        return [value.id for value in values]


def count(harness):
    with harness.SessionLocal() as db:
        return db.query(Task).count()


def test_confirm_only_creates_after_click_with_all_fields(harness):
    subject_id = subjects(harness, 'Базы данных')[0]
    offer = text(harness, 'сдать практику по бд завтра в 18 срочно')
    assert count(harness) == 0
    assert 'Новая задача' in offer.text and '<b>Сдать практику</b>' in offer.text
    assert '📚 Базы данных' in offer.text and '📅 Завтра, 18:00' in offer.text
    assert 'Высокий приоритет' in offer.text
    created = click(harness, offer, 'add_task_quick_create')
    assert 'Задача добавлена' in created.text
    assert 'Базы данных' in created.text and 'Завтра, 18:00' in created.text
    assert [[b['text'] for b in row] for row in created.reply_markup['inline_keyboard']] == [['📌 Все задачи', '➕ Ещё задачу']]
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert (task.title, task.deadline, task.subject_id, task.priority) == ('Сдать практику', datetime(2026, 10, 1, 18), subject_id, 'high')
    assert 'Сдать практику' in text(harness, '/tasks').text


def test_no_deadline_does_not_require_extra_steps(harness):
    offer = text(harness, 'купить тетрадь')
    assert 'Без дедлайна' in offer.text
    click(harness, offer, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        assert db.query(Task).one().deadline is None


def test_unknown_or_other_users_subject_is_not_attached(harness):
    subjects(harness, 'Базы данных', owner=harness.second_user_id)
    offer = text(harness, 'сдать практику по бд завтра')
    assert 'Базы данных' not in offer.text
    click(harness, offer, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert task.subject_id is None
        assert task.title == 'Сдать практику по бд'


def test_ambiguous_subject_choice_preserves_other_fields(harness):
    ids = subjects(harness, 'Базы данных', 'Безопасность данных')
    offer = text(harness, 'сдать практику по бд завтра в 18')
    assert 'несколько предметов' in offer.text
    assert not any('quick_create' in b.get('callback_data', '') for row in offer.reply_markup['inline_keyboard'] for b in row)
    selected = click(harness, offer, f'add_task_draft_subject:{ids[1]}')
    assert '📚 Безопасность данных' in selected.text
    assert '<b>Сдать практику</b>' in selected.text
    click(harness, selected, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        assert db.query(Task).one().subject_id == ids[1]


def test_ambiguous_subject_can_be_left_unassigned(harness):
    subjects(harness, 'Базы данных', 'Безопасность данных')
    offer = text(harness, 'сдать практику по бд завтра')
    selected = click(harness, offer, 'add_task_draft_subject:none')
    click(harness, selected, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert task.subject_id is None and task.title == 'Сдать практику по бд'


def test_past_time_warns_and_tomorrow_requires_another_confirmation(harness):
    offer = text(harness, 'сдать практику сегодня в 10')
    assert '⚠️ Это время сегодня уже прошло.' in offer.text
    assert count(harness) == 0
    adjusted = click(harness, offer, 'add_task_draft_tomorrow')
    assert 'Завтра, 10:00' in adjusted.text and count(harness) == 0
    click(harness, adjusted, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        assert db.query(Task).one().deadline == datetime(2026, 10, 1, 10)


@pytest.mark.parametrize('message', ['задача 29.09.2026', 'задача 31.02', 'задача в 25', 'задача завтра послезавтра'])
def test_past_or_invalid_date_has_no_create_button_and_cannot_be_bypassed(harness, message):
    offer = text(harness, message)
    edit = action(offer, 'add_task_quick_customize')
    forged = edit.replace('add_task_quick_customize', 'add_task_quick_create')
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._callback(forged))
    assert '⚠️' in reply.text
    assert count(harness) == 0


def test_confirmation_rechecks_time_if_deadline_passes(harness):
    offer = text(harness, 'задача сегодня в 13')
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW + timedelta(hours=2))):
        reply = click(harness, offer, 'add_task_quick_create')
    assert 'Это время сегодня уже прошло' in reply.text
    assert count(harness) == 0


def test_user_timezone_used_instead_of_server(harness):
    with harness.SessionLocal() as db:
        db.get(User, harness.first_user_id).telegram_morning_digest_timezone = 'Asia/Vladivostok'
        db.commit()
    offer = text(harness, 'задача сегодня в 18')  # It's 19:00 for this user.
    assert 'Это время сегодня уже прошло' in offer.text
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, datetime(2026, 9, 30, 20, tzinfo=UTC))):
        text(harness, '/cancel')
        offer = text(harness, 'задача завтра в 18')  # Local day is already October 1.
        click(harness, offer, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        assert db.query(Task).one().deadline == datetime(2026, 10, 2, 18)


@pytest.mark.parametrize('message,expected', [('привет', 'Привет!'), ('спасибо', 'Пожалуйста'), ('помощь', 'Что умеет'), ('что ты умеешь?', 'Что умеет'), ('как дела?', 'Напиши, что нужно')])
def test_conversation_has_no_draft(harness, message, expected):
    reply = text(harness, message)
    assert expected in reply.text
    with harness.SessionLocal() as db:
        assert not db.get(TelegramState, 'dialog:7001').data
    assert count(harness) == 0


@pytest.mark.parametrize('cancel', ['отмена', '/cancel', 'button'])
def test_cancellation_invalidates_create(harness, cancel):
    offer = text(harness, 'купить тетрадь')
    reply = click(harness, offer, 'add_task_cancel') if cancel == 'button' else text(harness, cancel)
    assert 'отмен' in reply.text.lower()
    assert 'устарело' in click(harness, offer, 'add_task_quick_create').text.lower()
    assert count(harness) == 0


def test_edit_uses_existing_flow_and_keeps_parsed_values(harness):
    sid = subjects(harness, 'Базы данных')[0]
    offer = text(harness, 'сдать практику по бд завтра в 18 срочно')
    step = click(harness, offer, 'add_task_quick_customize')
    assert 'Сейчас: Сдать практику' in step.text
    step = click(harness, step, 'add_task_keep')
    assert 'Когда дедлайн' in step.text and 'Сейчас: Завтра, 18:00' in step.text
    step = click(harness, step, 'add_task_keep')
    assert 'Сейчас: Базы данных' in step.text
    step = click(harness, step, 'add_task_keep')
    assert 'Сейчас: Высокий' in step.text
    step = click(harness, step, 'add_task_keep')
    click(harness, step, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert task.deadline == datetime(2026, 10, 1, 18)
        assert task.subject_id == sid and task.priority == 'high'


def test_edit_can_change_every_field(harness):
    sid = subjects(harness, 'Философия')[0]
    offer = text(harness, 'купить тетрадь')
    click(harness, offer, 'add_task_quick_customize')
    step = text(harness, 'Новое название')
    step = click(harness, step, 'add_task_deadline_custom')
    step = text(harness, 'послезавтра в 20')
    step = click(harness, step, f'add_task_subject:{sid}')
    step = click(harness, step, 'add_task_priority_low')
    click(harness, step, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert (task.title, task.deadline, task.subject_id, task.priority) == ('Новое название', datetime(2026, 10, 2, 20), sid, 'low')


def test_active_editor_does_not_parse_title_as_new_task(harness):
    text(harness, '/add_task')
    offer = text(harness, 'Исходная задача')
    click(harness, offer, 'add_task_quick_customize')
    reply = text(harness, 'выучить слова завтра в 18')
    assert 'Когда дедлайн' in reply.text
    with harness.SessionLocal() as db:
        assert db.get(TelegramState, 'dialog:7001').data['title'] == 'выучить слова завтра в 18'
    assert count(harness) == 0


def test_unlinked_user_cannot_create_or_read_draft(harness):
    offer = text(harness, 'купить тетрадь')
    assert 'Аккаунт не подключён' in text(harness, 'задача завтра', telegram_user_id=9999).text
    stolen = click(harness, offer, 'add_task_quick_create', telegram_user_id=9999)
    assert 'тетрадь' not in stolen.text
    assert count(harness) == 0


def test_other_linked_user_cannot_confirm_or_select_foreign_subject(harness):
    ids = subjects(harness, 'Базы данных', 'Безопасность данных')
    foreign = subjects(harness, 'Чужой секрет', owner=harness.second_user_id)[0]
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        db.commit()
    offer = text(harness, 'практика по бд завтра')
    stamp = action(offer, f'add_task_draft_subject:{ids[0]}').partition('|')[2]
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._callback(f'add_task_draft_subject:{foreign}|{stamp}'))
    assert 'Чужой секрет' not in reply.text
    offer = click(harness, offer, f'add_task_draft_subject:{ids[0]}')
    text(harness, 'Задача другого пользователя', telegram_user_id=7002, chat_id=8002)
    reply = click(harness, offer, 'add_task_quick_create', telegram_user_id=7002, chat_id=8002)
    assert 'устарело' in reply.text.lower()
    assert count(harness) == 0


@pytest.mark.parametrize('kind', ['text', 'callback'])
def test_group_has_no_access(harness, kind):
    offer = text(harness, 'купить тетрадь')
    update = harness._update('задача завтра', chat_id=-123) if kind == 'text' else harness._callback(action(offer, 'add_task_quick_create'), chat_id=-123)
    message = update['message'] if kind == 'text' else update['callback_query']['message']
    message['chat']['type'] = 'supergroup'
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, update)
        assert reply.text == 'Открой личный чат с ботом.'
        assert db.get(User, harness.first_user_id).telegram_chat_id == 8001
    assert count(harness) == 0


def test_repeat_callback_and_old_callback_after_new_draft_do_not_create_twice(harness):
    offer = text(harness, 'купить тетрадь')
    click(harness, offer, 'add_task_quick_create')
    assert 'устарело' in click(harness, offer, 'add_task_quick_create').text.lower()
    text(harness, 'купить ручку')
    assert 'устарело' in click(harness, offer, 'add_task_quick_create').text.lower()
    with harness.SessionLocal() as db:
        unsigned = handle_telegram_update(db, harness._callback('add_task_quick_create'))
    assert 'устарело' in unsigned.text.lower()
    assert count(harness) == 1


def deliver(harness, update, uid, send):
    with harness.SessionLocal() as db:
        process_update(db, {**update, 'update_id': uid}, send_message=send)


def test_repeat_update_and_lost_reply_use_existing_durable_outbox(harness):
    sent = []
    update = harness._update('задача завтра в 18')
    deliver(harness, update, 1, sent.append)
    deliver(harness, update, 1, sent.append)
    assert len(sent) == 1 and count(harness) == 0
    confirm = harness._callback(action(sent[0], 'add_task_quick_create'))
    with pytest.raises(TelegramAPIError):
        deliver(harness, confirm, 2, Mock(side_effect=TelegramAPIError(category='network')))
    assert count(harness) == 1
    with harness.SessionLocal() as db:
        row = db.get(TelegramUpdate, 2)
        assert row.status == 'pending'
        row.available_at = NOW.replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    sent.clear()
    deliver(harness, confirm, 2, sent.append)
    deliver(harness, confirm, 2, sent.append)
    deliver(harness, confirm, 3, sent.append)
    assert count(harness) == 1
    assert 'Задача добавлена' in sent[0].text and 'устарело' in sent[1].text.lower()


def test_draft_survives_actual_new_python_process(harness):
    offer = text(harness, 'задача завтра в 18')
    update = harness._callback(action(offer, 'add_task_quick_create'))
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
    assert 'Задача добавлена' in reply.text
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), json.dumps(update)], cwd=os.getcwd(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert count(harness) == 1


def test_expired_draft_cannot_be_confirmed(harness):
    offer = text(harness, 'задача завтра')
    with harness.SessionLocal() as db:
        row = db.get(TelegramState, 'dialog:7001')
        assert row.expires_at == NOW.replace(tzinfo=None) + timedelta(minutes=30)
        row.expires_at = NOW.replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    assert 'устарело' in click(harness, offer, 'add_task_quick_create').text.lower()
    assert count(harness) == 0


def test_deleted_subject_is_not_recreated_at_confirmation(harness):
    sid = subjects(harness, 'Базы данных')[0]
    offer = text(harness, 'практика по бд завтра')
    with harness.SessionLocal() as db:
        db.delete(db.get(Subject, sid))
        db.commit()
    success = click(harness, offer, 'add_task_quick_create')
    assert 'Базы данных' not in success.text
    with harness.SessionLocal() as db:
        assert db.query(Task).one().subject_id is None
        assert db.query(Subject).count() == 0


def test_created_task_is_visible_on_site_today_tasks_and_calendar(harness):
    offer = text(harness, 'выучить слова сегодня 20:30')
    click(harness, offer, 'add_task_quick_create')
    assert 'Выучить слова' in text(harness, '/tasks').text
    assert 'Выучить слова' in text(harness, '/today').text
    harness._login()
    assert 'Выучить слова' in harness.client.get('/tasks').text
    with harness.SessionLocal() as db:
        events = build_calendar_event_map(db.get(User, harness.first_user_id), db, 2026, 9)['event_map'][NOW.date()]
        assert any(event['type'] == 'task' and event['title'] == 'Выучить слова' for event in events)


def test_html_is_escaped_in_confirmation(harness):
    offer = text(harness, 'написать <эссе> завтра')
    assert '&lt;эссе&gt;' in offer.text and '<эссе>' not in offer.text
