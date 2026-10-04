from datetime import datetime, timedelta
import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.models import Task, TelegramState, User
from app.services.telegram_bot import handle_telegram_update
from app.services.telegram_task_parser import parse_task
from test_telegram_task_draft import harness, frozen_clock, NOW, text, click, action, subjects, count, deliver


def open_form(harness):
    menu = text(harness, '/start')
    reply = click(harness, menu, 'add_task_start')
    assert 'Опиши её одним сообщением.' in reply.text
    assert 'сделать Python на вторник' in reply.text
    return reply


def preview(harness, phrase):
    open_form(harness)
    return text(harness, phrase)


def assert_preview(reply):
    assert 'Всё верно?' in reply.text
    assert 'Когда дедлайн' not in reply.text
    assert 'К какому предмету' not in reply.text
    assert [[b['text'] for b in row] for row in reply.reply_markup['inline_keyboard']] == [
        ['✅ Создать', '✏️ Изменить'], ['❌ Отмена'],
    ]


def test_add_task_python_phrase_fills_fields_and_preserves_title(harness):
    sid = subjects(harness, 'Питон')[0]
    reply = preview(harness, 'сделать питон на вторник')
    assert_preview(reply)
    assert '<b>Сделать питон</b>' in reply.text
    assert '📚 Питон' in reply.text
    assert '📅 Вторник, 6 октября' in reply.text
    assert '23:59' not in reply.text
    assert '🟡 Средний приоритет' in reply.text
    assert count(harness) == 0
    click(harness, reply, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert (task.title, task.subject_id, task.deadline) == ('Сделать питон', sid, datetime(2026, 10, 6, 23, 59))


@pytest.mark.parametrize('phrase,title,deadline,priority,subject', [
    ('сдать практику по БД завтра в 18', 'Сдать практику', datetime(2026, 10, 1, 18), 'medium', 'Базы данных'),
    ('купить тетрадь', 'Купить тетрадь', None, 'medium', None),
    ('выучить слова завтра', 'Выучить слова', datetime(2026, 10, 1, 23, 59), 'medium', None),
    ('срочно сделать лабу завтра', 'Сделать лабу', datetime(2026, 10, 1, 23, 59), 'high', None),
    ('сдать практику для питона во вторник', 'Сдать практику', datetime(2026, 10, 6, 23, 59), 'medium', 'Питон'),
])
def test_add_task_immediately_previews_optional_fields(harness, phrase, title, deadline, priority, subject):
    ids = subjects(harness, 'Базы данных', 'Питон')
    reply = preview(harness, phrase)
    assert_preview(reply)
    assert f'<b>{title}</b>' in reply.text
    assert ('📚 ' + (subject or 'Без предмета')) in reply.text
    if not deadline: assert '📅 Без дедлайна' in reply.text
    click(harness, reply, 'add_task_quick_create')
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert (task.title, task.deadline, task.priority) == (title, deadline, priority)
        assert task.subject_id == (ids[0] if subject == 'Базы данных' else ids[1] if subject else None)


def test_ambiguous_subject_is_the_only_question(harness):
    ids = subjects(harness, 'Программирование', 'Программирование на Python')
    reply = preview(harness, 'сделать лабу по проге завтра')
    assert '📚 Какой предмет?' in reply.text
    assert 'Когда дедлайн' not in reply.text
    assert count(harness) == 0
    selected = click(harness, reply, f'add_task_draft_subject:{ids[1]}')
    assert_preview(selected)
    assert '📚 Программирование на Python' in selected.text
    assert '<b>Сделать лабу</b>' in selected.text
    assert '📅 Завтра' in selected.text and '23:59' not in selected.text


def test_ambiguous_subject_none_immediately_previews(harness):
    subjects(harness, 'Программирование', 'Программирование на Python')
    reply = preview(harness, 'сделать лабу по проге завтра')
    selected = click(harness, reply, 'add_task_draft_subject:none')
    assert_preview(selected)
    assert '📚 Без предмета' in selected.text
    assert 'Сделать лабу по проге' in selected.text


def test_past_time_only_offers_targeted_correction(harness):
    reply = preview(harness, 'сделать лабу сегодня в 10')
    assert 'Это время сегодня уже прошло.' in reply.text
    assert '📅 Завтра в 10:00' in str(reply.reply_markup)
    assert 'Когда дедлайн' not in reply.text
    corrected = click(harness, reply, 'add_task_draft_tomorrow')
    assert_preview(corrected)
    assert 'Завтра, 10:00' in corrected.text and count(harness) == 0


def test_editor_opens_only_on_modify_and_keeps_values(harness):
    reply = preview(harness, 'сделать питон на вторник')
    step = click(harness, reply, 'add_task_quick_customize')
    assert 'Сейчас: Сделать питон' in step.text
    step = click(harness, step, 'add_task_keep')
    assert 'Когда дедлайн' in step.text
    assert 'Сейчас: Вторник, 6 октября' in step.text and '23:59' not in step.text
    step = click(harness, step, 'add_task_keep')
    assert 'К какому предмету' in step.text
    step = click(harness, step, 'add_task_keep')
    step = click(harness, step, 'add_task_keep')
    assert_preview(step)


@pytest.mark.parametrize('phrase,show_time', [('задача во вторник в 18', '18:00'), ('задача во вторник в 23:59', '23:59'), ('задача во вторник', None)])
def test_preview_distinguishes_explicit_time_from_default(harness, phrase, show_time):
    reply = preview(harness, phrase)
    if show_time:
        assert f'📅 Вторник, 6 октября · {show_time}' in reply.text
    else:
        assert '📅 Вторник, 6 октября\n' in reply.text and '23:59' not in reply.text


def test_custom_editor_date_updates_explicit_time_flag(harness):
    reply = preview(harness, 'задача во вторник в 18')
    step = click(harness, reply, 'add_task_quick_customize')
    step = click(harness, step, 'add_task_keep')
    click(harness, step, 'add_task_deadline_custom')
    step = text(harness, 'в пятницу')
    step = click(harness, step, 'add_task_keep')
    step = click(harness, step, 'add_task_keep')
    assert_preview(step)
    assert '23:59' not in step.text


def test_plain_text_and_add_button_share_exact_preview(harness):
    subjects(harness, 'Базы данных')
    phrase = 'сдать практику по бд завтра в 18'
    direct = text(harness, phrase)
    text(harness, '/cancel')
    from_button = preview(harness, phrase)
    assert from_button.text == direct.text
    assert [[b['text'] for b in r] for r in from_button.reply_markup['inline_keyboard']] == [[b['text'] for b in r] for r in direct.reply_markup['inline_keyboard']]


def test_repeated_update_and_confirm_create_exactly_one_task(harness):
    open_form(harness)
    sent = []
    update = harness._update('купить тетрадь')
    deliver(harness, update, 1, sent.append)
    deliver(harness, update, 1, sent.append)
    assert len(sent) == 1 and count(harness) == 0
    confirm = harness._callback(action(sent[0], 'add_task_quick_create'))
    deliver(harness, confirm, 2, sent.append)
    deliver(harness, confirm, 2, sent.append)
    deliver(harness, confirm, 3, sent.append)
    assert count(harness) == 1


def test_restart_restores_preview_without_implicit_time(harness):
    subjects(harness, 'Питон')
    reply = preview(harness, 'сделать питон на вторник')
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
    assert 'Вторник, 6 октября' in reply.text and '23:59' not in reply.text
    assert 'Задача добавлена' in reply.text
engine.dispose()
'''
    update = harness._callback(action(reply, 'add_task_quick_create'))
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), json.dumps(update)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert count(harness) == 1


def test_ttl_remains_thirty_minutes(harness):
    reply = preview(harness, 'купить тетрадь')
    with harness.SessionLocal() as db:
        row = db.get(TelegramState, 'dialog:7001')
        assert row.expires_at == NOW.replace(tzinfo=None) + timedelta(minutes=30)
        row.expires_at = NOW.replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    assert 'устарело' in click(harness, reply, 'add_task_quick_create').text
    assert count(harness) == 0


def test_unlinked_and_group_cannot_use_add_flow(harness):
    with harness.SessionLocal() as db:
        unlinked = handle_telegram_update(db, harness._callback('add_task_start', telegram_user_id=9999))
        assert 'Аккаунт не подключён' in unlinked.text
        update = harness._callback('add_task_start', chat_id=-55)
        update['callback_query']['message']['chat']['type'] = 'supergroup'
        assert handle_telegram_update(db, update).text == 'Открой личный чат с ботом.'
        assert db.get(User, harness.first_user_id).telegram_chat_id == 8001
    assert count(harness) == 0


def test_foreign_subject_not_recognized_and_other_user_cannot_confirm(harness):
    subjects(harness, 'Питон', owner=harness.second_user_id)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.second_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7002, 8002
        db.commit()
    reply = preview(harness, 'сделать питон на вторник')
    assert '📚 Без предмета' in reply.text
    stolen = click(harness, reply, 'add_task_quick_create', telegram_user_id=7002, chat_id=8002)
    assert 'устарело' in stolen.text and count(harness) == 0


@pytest.mark.parametrize('phrase,name,title', [
    ('сделать питон на вторник', 'Питон', 'Сделать питон'),
    ('сделать Python на вторник', 'Питон', 'Сделать Python'),
    ('сдать практику по питону во вторник', 'Питон', 'Сдать практику'),
    ('подготовить доклад для философии на пятницу', 'Философия', 'Подготовить доклад'),
])
def test_parser_context_and_implicit_mentions(phrase, name, title):
    parsed = parse_task(phrase, now=datetime(2026, 10, 1, 12), subjects=[(1, name)])
    assert parsed.title == title and parsed.subject_ids == (1,) and not parsed.time_explicit
