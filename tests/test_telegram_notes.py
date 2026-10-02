"""Quick notes share website records; private routing and durable state are enforced."""
from datetime import timedelta
import json
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from app.models import Note, Task, TelegramState, User
from app.services import telegram_notes
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, handle_telegram_update
from app.services.telegram_delivery import process_update
from test_telegram_task_draft import NOW, action, click, count, frozen_clock, harness, text


@pytest.fixture(autouse=True)
def notes_clock():
    with patch('app.services.telegram_notes.utcnow', return_value=NOW.replace(tzinfo=None)):
        yield


def callback(harness, action, **kwargs):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._callback(action, **kwargs))


def start(harness):
    return callback(harness, 'note_start')


def button_action(reply, prefix):
    return next(b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row
                if b.get('callback_data', '').startswith(prefix))


def notes(harness):
    with harness.SessionLocal() as db:
        return [(n.id, n.title, n.content) for n in db.query(Note).order_by(Note.id).all()]


def test_main_menu_note_prompt_and_six_commands(harness):
    menu = text(harness, '/start')
    rows = menu.reply_markup['inline_keyboard']
    assert [[b['text'] for b in row] for row in rows] == [
        ['📍 Сейчас'], ['📅 Сегодня', '📆 Завтра'], ['🗓 Неделя', '📌 Задачи'],
        ['➕ Добавить задачу'], ['📝 Заметка'], ['⚙️ Настройки', '🌐 Сайт']]
    reply = callback(harness, rows[4][0]['callback_data'])
    assert '📝 <b>Новая заметка</b>' in reply.text
    assert 'Напиши текст одним сообщением.' in reply.text
    assert reply.reply_markup['inline_keyboard'][0][0]['text'] == '❌ Отмена'
    assert len(BOT_COMMANDS) == 6 and 'note' not in [item['command'] for item in BOT_COMMANDS]


@pytest.mark.parametrize('message', [
    'На БД повторить оконные функции', 'Review window functions', '📚 Повторить JOIN 🚀',
    'Первая строка\nВторая строка\n\nТретья строка', 'привет', 'спасибо',
])
def test_text_saved_directly_without_task_parser(harness, message):
    start(harness)
    with patch('app.services.telegram_bot.parse_task', side_effect=AssertionError('must not parse a note')):
        reply = text(harness, message)
    assert '✅ Заметка сохранена' in reply.text and count(harness) == 0
    stored = notes(harness)
    assert len(stored) == 1
    _, title, content = stored[0]
    assert title + ('\n' + content if content else '') == message
    assert 'note_delete:' in str(reply.reply_markup)
    assert '/notes?note=' in str(reply.reply_markup)
    assert 'note_start' in str(reply.reply_markup)


@pytest.mark.parametrize('message', ['я' * 10000, 'Long heading ' * 30 + '\n' + 'text\n' * 700, 'Короткий заголовок\n' + 'x' * 10000], ids=['single-line', 'long-heading', 'max-body'])
def test_long_text_is_complete_but_preview_is_short(harness, message):
    start(harness)
    reply = text(harness, message)
    _, title, body = notes(harness)[0]
    assert body == message.strip() or title + '\n' + body == message.strip()
    assert len(title) <= 60
    assert len(reply.text) < 1500 and '…' in reply.text


@pytest.mark.parametrize('message', ['заметка: сделать питон завтра в 18', 'ЗАМЕТКА: English notes', 'заметка : строка 1\nстрока 2'])
def test_explicit_prefix_skips_task_parser(harness, message):
    with patch('app.services.telegram_bot.parse_task', side_effect=AssertionError('not a task')):
        reply = text(harness, message)
    assert 'Заметка сохранена' in reply.text
    assert len(notes(harness)) == 1 and count(harness) == 0
    assert 'заметка:' not in notes(harness)[0][1].lower()


def test_regular_phrase_still_creates_task_after_confirmation(harness):
    reply = text(harness, 'сделать питон завтра')
    assert 'Новая задача' in reply.text and notes(harness) == []
    click(harness, reply, 'add_task_quick_create')
    assert count(harness) == 1


@pytest.mark.parametrize('how', ['command', 'button', 'word', 'old_task_cancel'])
def test_cancel_returns_to_task_parser(harness, how):
    prompt = start(harness)
    if how == 'command':
        reply = text(harness, '/cancel')
    elif how == 'word':
        reply = text(harness, 'отмена')
    elif how == 'old_task_cancel':
        reply = callback(harness, 'add_task_cancel')
    else:
        reply = callback(harness, button_action(prompt, 'note_cancel:'))
    assert reply.text == '❌ Создание заметки отменено.'
    assert notes(harness) == []
    assert 'Новая задача' in text(harness, 'купить тетрадь').text


def test_old_cancel_cannot_close_new_note_flow(harness):
    old = start(harness)
    start(harness)
    assert 'устарело' in callback(harness, button_action(old, 'note_cancel:')).text
    assert 'Заметка сохранена' in text(harness, 'Новая заметка').text


@pytest.mark.parametrize('seconds', [1799, 1800, 1801])
def test_note_ttl_boundaries(harness, seconds):
    start(harness)
    with patch('app.services.telegram_notes.utcnow', return_value=(NOW + timedelta(seconds=seconds)).replace(tzinfo=None)):
        reply = text(harness, 'сделать завтра')
    if seconds < 1800:
        assert 'Заметка сохранена' in reply.text
    else:
        assert reply.text == '⚠️ Создание заметки устарело.'
        assert button_action(reply, 'note_start') == 'note_start'
        assert notes(harness) == [] and count(harness) == 0


def test_restart_between_button_and_text(harness):
    start(harness)
    script = '''
import json, sys
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Note, Task
from app.services.telegram_bot import handle_telegram_update
engine = create_engine(sys.argv[1])
with Session(engine) as db, patch('app.services.telegram_notes.utcnow', return_value=datetime(2026,9,30,9,1)):
    reply = handle_telegram_update(db, json.loads(sys.argv[2]))
    assert 'Заметка сохранена' in reply.text
    assert db.query(Note).one().title == 'Записано после рестарта'
    assert db.query(Task).count() == 0
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), json.dumps(harness._update('Записано после рестарта'))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_group_does_not_create_read_or_change_private_chat(harness):
    reply = text(harness, 'заметка: Личный текст')
    for update in [harness._update('заметка: Чужая группа', chat_id=-100),
                   harness._callback('note_start', chat_id=-100),
                   harness._callback(button_action(reply, 'note_delete:'), chat_id=-100)]:
        message = update.get('message') or update['callback_query']['message']
        message['chat']['type'] = 'supergroup'
        with harness.SessionLocal() as db:
            response = handle_telegram_update(db, update)
            assert 'личный чат' in response.text and 'Личный текст' not in response.text
            assert db.get(User, harness.first_user_id).telegram_chat_id == 8001
    assert len(notes(harness)) == 1


def test_unlinked_user_cannot_start_or_save(harness):
    with harness.SessionLocal() as db:
        from app.services.telegram_bot import clear_telegram_link
        clear_telegram_link(db.get(User, harness.first_user_id))
        db.commit()
    assert 'подключи' in start(harness).text
    assert 'подключи' in text(harness, 'заметка: текст').text
    assert notes(harness) == []


def test_relink_does_not_reuse_waiting_state(harness):
    start(harness)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_linked_at = NOW.replace(tzinfo=None)
        db.commit()
    assert 'устарело' in text(harness, 'Личный текст').text
    assert notes(harness) == []


def test_delete_requires_confirmation_and_repeated_callback_is_safe(harness):
    saved = text(harness, 'заметка: Удаляемая заметка')
    confirm = callback(harness, button_action(saved, 'note_delete:'))
    assert 'Удалить эту заметку?' in confirm.text and len(notes(harness)) == 1
    delete = button_action(confirm, 'note_delete_confirm:')
    assert callback(harness, delete).text == '🗑 Заметка удалена'
    assert notes(harness) == []
    assert 'уже нет' in callback(harness, delete).text


def test_keep_invalidates_delete_confirmation(harness):
    saved = text(harness, 'заметка: Оставить')
    confirm = callback(harness, button_action(saved, 'note_delete:'))
    assert 'оставлена' in callback(harness, button_action(confirm, 'note_keep:')).text
    assert 'устарело' in callback(harness, button_action(confirm, 'note_delete_confirm:')).text
    assert len(notes(harness)) == 1


def test_delete_cannot_bypass_confirmation(harness):
    text(harness, 'заметка: Важная заметка')
    note_id = notes(harness)[0][0]
    assert 'устарело' in callback(harness, f'note_delete_confirm:{note_id}:forged').text
    assert len(notes(harness)) == 1


def test_ownership_checked_at_prompt_and_immediately_before_delete(harness):
    saved = text(harness, 'заметка: Секрет владельца')
    confirm = callback(harness, button_action(saved, 'note_delete:'))
    with harness.SessionLocal() as db:
        other = db.get(User, harness.second_user_id)
        other.telegram_user_id, other.telegram_chat_id = 7002, 8002
        db.commit()
    for value in [button_action(saved, 'note_delete:'), button_action(confirm, 'note_delete_confirm:')]:
        reply = callback(harness, value, telegram_user_id=7002, chat_id=8002)
        assert 'недоступна' in reply.text and 'Секрет' not in reply.text
    with harness.SessionLocal() as db:
        db.query(Note).one().user_id = harness.second_user_id
        db.commit()
    assert 'недоступна' in callback(harness, button_action(confirm, 'note_delete_confirm:')).text
    assert len(notes(harness)) == 1


def website_post(harness, url, data=None):
    csrf = harness._csrf(harness.client.get('/notes').text)
    return harness.client.post(url, data={'csrf_token': csrf, **(data or {})}, follow_redirects=False)


def test_shared_notes_visible_on_site_and_site_delete_invalidates_button(harness):
    harness._login()
    saved = text(harness, 'заметка: Оконные функции\nROW_NUMBER и LAG')
    page = harness.client.get('/notes')
    assert page.status_code == 200 and 'Оконные функции' in page.text and 'ROW_NUMBER и LAG' in page.text
    note_id = notes(harness)[0][0]
    assert website_post(harness, f'/notes/delete/{note_id}').status_code == 302
    assert 'уже нет' in callback(harness, button_action(saved, 'note_delete:')).text
    assert notes(harness) == []


def test_site_edit_is_read_fresh_and_requires_new_confirmation(harness):
    harness._login()
    saved = text(harness, 'заметка: Исходный текст')
    confirm = callback(harness, button_action(saved, 'note_delete:'))
    note_id = notes(harness)[0][0]
    assert website_post(harness, f'/notes/edit/{note_id}', {'title': 'Правка на сайте', 'content': 'Актуальная версия'}).status_code == 302
    updated = callback(harness, button_action(confirm, 'note_delete_confirm:'))
    assert 'Заметка изменилась' in updated.text and 'Актуальная версия' in updated.text
    assert 'Исходный текст' not in updated.text and len(notes(harness)) == 1
    assert 'удалена' in callback(harness, button_action(updated, 'note_delete_confirm:')).text


def test_existing_site_note_not_duplicated(harness):
    harness._login()
    assert website_post(harness, '/notes/add', {'title': 'Создано на сайте', 'content': 'Существующий текст'}).status_code == 302
    original = notes(harness)[0]
    start(harness)
    text(harness, 'Новая заметка из Telegram')
    assert len(notes(harness)) == 2 and notes(harness)[0] == original
    callback(harness, f'note_delete:{original[0]}')
    assert len(notes(harness)) == 2


@pytest.mark.parametrize('invalid', ['', 'заметка: ', 'x' * 10001, 'a\x00b'])
def test_invalid_input_does_not_save_or_fall_through_to_tasks(harness, invalid):
    start(harness)
    reply = text(harness, invalid)
    assert '⚠️' in reply.text and notes(harness) == [] and count(harness) == 0
    assert 'Заметка сохранена' in text(harness, 'Исправленная заметка').text


def test_preview_html_escaped(harness):
    reply = text(harness, 'заметка: <b>& HTML</b>')
    assert '&lt;b&gt;&amp; HTML&lt;/b&gt;' in reply.text
    assert notes(harness)[0][1] == '<b>& HTML</b>'


def test_duplicate_updates_and_delivery_failure_do_not_duplicate_note(harness):
    sender = Mock(side_effect=[TelegramAPIError(category='network'), None])
    update = {**harness._update('заметка: Не дублировать'), 'update_id': 100}
    with harness.SessionLocal() as db:
        with pytest.raises(TelegramAPIError):
            process_update(db, update, send_message=sender)
    assert len(notes(harness)) == 1
    with harness.SessionLocal() as db, patch('app.services.telegram_delivery.utcnow', return_value=(NOW + timedelta(minutes=1)).replace(tzinfo=None)):
        process_update(db, update, send_message=sender)
        process_update(db, update, send_message=sender)
    assert len(notes(harness)) == 1 and sender.call_count == 2


def test_note_wins_over_task_draft_but_preserves_it(harness):
    offer = text(harness, 'купить тетрадь')
    start(harness)
    assert 'Заметка сохранена' in text(harness, 'выучить английский завтра').text
    assert count(harness) == 0 and len(notes(harness)) == 1
    assert 'Задача добавлена' in click(harness, offer, 'add_task_quick_create').text


def test_explicit_note_wins_over_existing_task_editor(harness):
    offer = text(harness, 'купить тетрадь')
    click(harness, offer, 'add_task_quick_customize')
    assert 'Заметка сохранена' in text(harness, 'заметка: Это текст заметки').text
    assert count(harness) == 0 and len(notes(harness)) == 1


def test_special_reschedule_flow_has_priority(harness):
    from app.services.telegram_bot import AddTaskDialog
    from app.services.telegram_task_actions import RESCHEDULE_DATE
    from dataclasses import asdict
    with harness.SessionLocal() as db:
        row = TelegramState(key='dialog:7001', data=asdict(AddTaskDialog(user_id=harness.first_user_id, chat_id=8001, step=RESCHEDULE_DATE)), expires_at=NOW.replace(tzinfo=None)+timedelta(minutes=30))
        db.add(row)
        db.commit()
    assert 'заверши перенос' in start(harness).text
    text(harness, 'заметка: не дата')
    assert notes(harness) == []


def test_delete_confirmation_expires(harness):
    saved = text(harness, 'заметка: Сохранить')
    confirm = callback(harness, button_action(saved, 'note_delete:'))
    with patch('app.services.telegram_notes.utcnow', return_value=(NOW + timedelta(minutes=30)).replace(tzinfo=None)):
        assert 'устарело' in callback(harness, button_action(confirm, 'note_delete_confirm:')).text
    assert len(notes(harness)) == 1


def test_flow_users_are_independent(harness):
    start(harness)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.second_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7002, 8002
        db.commit()
    callback(harness, 'note_start', telegram_user_id=7002, chat_id=8002)
    text(harness, 'Вторая заметка', telegram_user_id=7002, chat_id=8002)
    text(harness, 'Первая заметка')
    with harness.SessionLocal() as db:
        assert db.query(Note).filter_by(user_id=harness.first_user_id).one().title == 'Первая заметка'
        assert db.query(Note).filter_by(user_id=harness.second_user_id).one().title == 'Вторая заметка'


def test_note_flow_duplicate_message_update_does_not_become_task(harness):
    start(harness)
    update = {**harness._update('сделать питон завтра'), 'update_id': 200}
    with harness.SessionLocal() as db:
        process_update(db, update, send_message=lambda _: None)
        process_update(db, update, send_message=lambda _: None)
    assert len(notes(harness)) == 1 and count(harness) == 0


@pytest.mark.parametrize('value', ['note_delete:-1', 'note_delete:not-an-id', 'note_delete:99999999999999999999999999999'])
def test_malformed_delete_callback_is_safe(harness, value):
    assert 'недоступна' in callback(harness, value).text
