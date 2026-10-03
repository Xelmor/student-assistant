"""Live-data search, deterministic ranking, dialog precedence and private ownership."""
from datetime import UTC, datetime, time, timedelta
import json
import subprocess
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.models import AcademicEvent, Note, Subject, Task, TelegramState, User
from app.services import telegram_search as search
from app.services.telegram_bot import BOT_COMMANDS, clear_telegram_link, handle_telegram_update
from test_telegram_now import add_lesson
from test_telegram_task_draft import NOW, click, count, frozen_clock, harness, text

LOCAL = NOW.astimezone(ZoneInfo('Europe/Moscow'))


@pytest.fixture(autouse=True)
def search_clock():
    with patch.object(search, 'utcnow', return_value=NOW.replace(tzinfo=None)):
        yield


def callback(harness, action, **kwargs):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._callback(action, **kwargs))


def buttons(reply):
    return [b for row in reply.reply_markup['inline_keyboard'] for b in row]


def more(reply, kind):
    return next(b['callback_data'] for b in buttons(reply) if f':{kind}:' in b.get('callback_data', ''))


def seed(harness, model=Task, **values):
    with harness.SessionLocal() as db:
        obj = model(user_id=harness.first_user_id, **values)
        db.add(obj)
        db.commit()
        return obj.id


def collect(harness, query, now=LOCAL):
    with harness.SessionLocal() as db:
        return search.collect(db, db.get(User, harness.first_user_id), query, now)


@pytest.mark.parametrize('query,expected', [
    ('БД', 'бд'), ('Бд', 'бд'), ('бд', 'бд'), (' ЁЛКА ', 'елка'),
    ('  базы   данных\n SQL ', 'базы данных sql'), ('Базы—данных, SQL!', 'базы данных sql'),
    ('Straße', 'strasse'), ('', ''), ('  !!! ', ''), ('я', 'я'),
])
def test_normalization(query, expected):
    assert search.normalize_query(query) == expected


def test_prompt_menu_commands_and_query_finishes_flow(harness):
    seed(harness, title='Практика БД')
    menu = text(harness, '/start')
    assert ['📝 Заметка', '🔎 Поиск'] in [[b['text'] for b in row] for row in menu.reply_markup['inline_keyboard']]
    prompt = click(harness, menu, 'search')
    assert 'Что найти?' in prompt.text and 'оконные функции' in prompt.text
    assert buttons(prompt)[0]['text'] == '❌ Отмена'
    assert len(BOT_COMMANDS) == 6 and all(c['command'] != 'search' for c in BOT_COMMANDS)
    reply = text(harness, 'БД')
    assert 'Практика БД' in reply.text
    with harness.SessionLocal() as db:
        assert db.get(TelegramState, 'search-flow:7001').data == {}
    assert 'Новая задача' in text(harness, 'купить тетрадь').text


@pytest.mark.parametrize('prefix', ['поиск:', 'найти:', 'ПОИСК :', 'Найти:'])
def test_explicit_prefix_never_calls_task_parser(harness, prefix):
    seed(harness, title='Практика по БД')
    with patch('app.services.telegram_bot.parse_task', side_effect=AssertionError('search is not a task')):
        reply = text(harness, prefix + ' БД')
    assert 'Практика по БД' in reply.text and count(harness) == 1


@pytest.mark.parametrize('query', ['', ' ', 'я', '!!!', 'я !'])
def test_short_query_does_not_query_records_and_can_retry(harness, query):
    with patch.object(search, 'collect', side_effect=AssertionError('expensive search')):
        assert 'хотя бы 2' in text(harness, 'поиск:' + query).text
    assert 'ничего не найдено' in text(harness, 'бд').text
    assert count(harness) == 0


def test_long_query_is_rejected_and_html_is_escaped(harness):
    assert '200 символов' in text(harness, 'поиск:' + 'а' * 201).text
    reply = text(harness, '<script>')
    assert '&lt;script&gt;' in reply.text and '<script>' not in reply.text


def test_task_fields_completed_and_relevance(harness):
    subject = seed(harness, Subject, name='БД')
    ids = [seed(harness, title='БД'), seed(harness, title='БД практика'),
           seed(harness, title='Практика БД'), seed(harness, title='Отчёт', subject_id=subject),
           seed(harness, title='Описание', description='Выучить БД'),
           seed(harness, title='БД', is_completed=True)]
    results = collect(harness, 'бд')['tasks']
    assert [r['id'] for r in results] == ids
    assert results[-1]['details'] == '✅ Выполнено'


def test_task_ties_deadline_order(harness):
    expected = []
    for deadline in [LOCAL.replace(tzinfo=None) - timedelta(days=1), datetime(2026,9,30,18), datetime(2026,10,1,18), None]:
        expected.append(seed(harness, title='БД', deadline=deadline))
    assert [r['id'] for r in collect(harness, 'бд')['tasks']] == expected
    assert 'Просрочено' in collect(harness, 'бд')['tasks'][0]['details']
    assert 'Сегодня' in collect(harness, 'бд')['tasks'][1]['details']


def test_tokens_can_match_across_fields_without_semantic_aliases(harness):
    seed(harness, title='Практика', description='Базы данных')
    assert len(collect(harness, 'данных практика')['tasks']) == 1
    assert collect(harness, 'бд')['tasks'] == []


def test_notes_full_text_case_freshness_and_preview(harness):
    old = seed(harness, Note, title='Конспект', content='Начало ' + 'х' * 3000 + ' ОКОННЫЕ функции', created_at=datetime(2026,9,1))
    new = seed(harness, Note, title='Конспект', content='Оконные функции ' + 'х' * 2000, created_at=datetime(2026,9,30))
    results = collect(harness, 'оконные')['notes']
    assert [r['id'] for r in results] == [new, old]
    reply = text(harness, 'поиск: оконные')
    assert len(reply.text) < 600 and '…' in reply.text
    with harness.SessionLocal() as db:
        assert len(db.get(Note, old).content) > 3000


@pytest.mark.parametrize('query', ['Математика', '301', 'Сидоров'])
def test_class_fields_and_future_occurrences(harness, query):
    with harness.SessionLocal() as db:
        lesson = add_lesson(db, harness, start='13:00', day=LOCAL.date())
        lesson.subject.teacher = 'Сидоров'
        db.commit()
    results = collect(harness, query)['classes']
    assert len(results) == 5
    assert results[0]['start'].date() == LOCAL.date()
    assert 'Ауд. 301' in results[0]['details']
    assert all(r['start'] >= LOCAL for r in results)


def test_cancelled_and_moved_class_uses_calendar(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, title='БД отменена', day=LOCAL.date(), start='13:00')
        db.add_all([
            AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=LOCAL.date()),
            AcademicEvent(user_id=harness.first_user_id, title='БД перенесена', event_type='changed_class',
                          event_date=LOCAL.date()+timedelta(days=1), start_time=time(14), end_time=time(15), room='205'),
        ])
        db.commit()
    results = collect(harness, 'бд')['classes']
    assert results[0]['title'] == 'БД перенесена'
    assert results[0]['start'].date() == LOCAL.date()+timedelta(days=1)
    assert '14:00–15:00' in results[0]['details']
    assert not any(r['start'].date() == LOCAL.date() for r in results)


def test_horizon_exact_start_timezone_and_missing_room(harness):
    local = NOW.astimezone(ZoneInfo('Asia/Novosibirsk'))  # 16:00, unlike server/project.
    for offset, hour in [(0,15), (0,16), (29,17), (30,17)]:
        seed(harness, AcademicEvent, title=f'БД {offset} {hour}', event_type='changed_class',
             event_date=local.date()+timedelta(days=offset), start_time=time(hour), end_time=time(hour+1))
    results = collect(harness, 'бд', now=local)['classes']
    assert [r['title'] for r in results] == ['БД 0 16', 'БД 29 17']
    assert all('Ауд.' not in r['details'] for r in results)


def test_user_timezone_used_by_callback_after_midnight(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_timezone = 'Asia/Novosibirsk'
        db.commit()
    seed(harness, AcademicEvent, title='БД завтра', event_type='changed_class', event_date=datetime(2026,10,1).date(), start_time=time(0,30), end_time=time(2))
    from app.services.telegram_digest import digest_local_datetime
    instant = datetime(2026,9,30,17,15,tzinfo=UTC)
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, instant)):
        assert 'БД завтра' in text(harness, 'поиск: бд').text


@pytest.mark.parametrize('kind,model', [('tasks',Task), ('notes',Note), ('classes',AcademicEvent)])
def test_pagination_all_categories_and_live_data(harness, kind, model):
    for n in range(12):
        extra = {'event_type':'changed_class', 'event_date':LOCAL.date()+timedelta(days=1), 'start_time':time(10), 'end_time':time(11)} if kind == 'classes' else {}
        seed(harness, model, title=f'БД {n:02}', **extra)
    first = text(harness, 'поиск: бд')
    assert 'Показано 5 из 12' in first.text
    second = callback(harness, more(first, kind))
    assert 'Показано 6–10 из 12' in second.text
    third_action = next(b['callback_data'] for b in buttons(second) if b['text'].startswith(('📌 Ещё','📝 Ещё','🎓 Ещё')))
    third = callback(harness, third_action)
    assert 'Показано 11–12 из 12' in third.text
    assert all(len(b.get('callback_data','').encode()) <= 64 for b in buttons(second))
    with harness.SessionLocal() as db:
        db.query(model).filter(model.user_id == harness.first_user_id).delete()
        db.commit()
    assert 'устарел' in callback(harness, third_action).text


def test_result_length_emoji_html_and_all_groups(harness):
    for n in range(6):
        seed(harness, title='БД ' + '<&😀' * 40)
        seed(harness, Note, title='БД ' + '<&😀' * 40, content='>&😀' * 2000)
        seed(harness, AcademicEvent, title='БД ' + '<&😀' * 40, event_type='changed_class',
             event_date=LOCAL.date()+timedelta(days=1), start_time=time(10), end_time=time(11), room='😀' * 50)
    reply = text(harness, 'поиск: бд')
    assert len(reply.text.encode('utf-16-le'))//2 < 4096
    assert all(label in reply.text for label in ('📌 Задачи','📝 Заметки','🎓 Занятия'))
    assert '&lt;' in reply.text and '<&' not in reply.text


@pytest.mark.parametrize('how', ['command','button','word','emoji','legacy'])
def test_cancel_and_normal_task_after(harness, how):
    prompt = callback(harness, 'search')
    if how == 'button':
        reply = callback(harness, buttons(prompt)[0]['callback_data'])
    elif how == 'legacy':
        reply = callback(harness, 'add_task_cancel')
    else:
        reply = text(harness, {'command':'/cancel','word':'отмена','emoji':'❌ Отмена'}[how])
    assert 'Поиск отменён' in reply.text
    assert 'Новая задача' in text(harness, 'купить тетрадь').text


def test_back_exits_waiting_and_old_cancel_does_not_cancel_new_search(harness):
    old = callback(harness, 'search')
    callback(harness, 'search')
    assert 'устарел' in callback(harness, buttons(old)[0]['callback_data']).text
    assert 'ничего не найдено' in text(harness, 'нейросети').text
    callback(harness, 'search')
    text(harness, '/start')
    assert 'Новая задача' in text(harness, 'купить тетрадь').text


@pytest.mark.parametrize('seconds', [1799,1800,1801])
def test_ttl_boundary_no_task_on_expired_query(harness, seconds):
    callback(harness, 'search')
    with patch.object(search, 'utcnow', return_value=(NOW+timedelta(seconds=seconds)).replace(tzinfo=None)):
        reply = text(harness, 'купить тетрадь')
    assert ('ничего не найдено' if seconds < 1800 else 'Поиск устарел') in reply.text
    assert count(harness) == 0


def test_restart_preserves_flow(harness):
    callback(harness, 'search')
    seed(harness, title='БД после рестарта')
    script = '''
import sys,json
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.telegram_bot import handle_telegram_update
engine=create_engine(sys.argv[1])
with Session(engine) as db, patch('app.services.telegram_search.utcnow', return_value=datetime(2026,9,30,9,1)):
    reply=handle_telegram_update(db,json.loads(sys.argv[2]))
    assert 'БД после рестарта' in reply.text, reply.text
engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script, str(harness.engine.url), json.dumps(harness._update('бд'))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_notes_take_priority_but_search_beats_note_prefix_without_note_flow(harness):
    callback(harness, 'note_start')
    assert 'заверши заметку' in callback(harness, 'search').text
    assert 'Заметка сохранена' in text(harness, 'поиск: это заметка').text
    callback(harness, 'search')
    assert 'ничего не найдено' in text(harness, 'заметка: не сохранять').text
    with harness.SessionLocal() as db:
        assert db.query(Note).count() == 1
    assert count(harness) == 0


def test_search_consumes_greetings_before_intents(harness):
    callback(harness, 'search')
    assert 'ничего не найдено' in text(harness, 'привет').text


def test_active_task_editor_keeps_priority(harness):
    offer = text(harness, 'купить тетрадь')
    click(harness, offer, 'add_task_quick_customize')
    assert 'заверши действие' in callback(harness, 'search').text
    assert 'Результаты' not in text(harness, 'поиск: бд').text
    with harness.SessionLocal() as db:
        assert db.get(TelegramState, 'search-flow:7001') is None
    assert count(harness) == 0


def test_task_reschedule_keeps_priority(harness):
    from test_telegram_task_actions import press
    seed(harness, title='Дедлайн', deadline=datetime(2026,10,1,18))
    step = press(harness, text(harness, '/tasks'), 'task_reschedule')
    click(harness, step, 'add_task_reschedule_custom')
    assert 'заверши действие' in callback(harness, 'search').text
    assert 'Результаты' not in text(harness, 'поиск: завтра').text


def test_foreign_data_and_cross_owner_subject_never_returned(harness):
    with harness.SessionLocal() as db:
        subject = Subject(user_id=harness.second_user_id, name='СЕКРЕТ', teacher='Секретный учитель')
        db.add(subject); db.flush()
        db.add_all([Task(user_id=harness.second_user_id, title='СЕКРЕТ'),
                    Note(user_id=harness.second_user_id, title='СЕКРЕТ', content='СЕКРЕТ'),
                    Task(user_id=harness.first_user_id, title='Моя задача', subject_id=subject.id)])
        add_lesson(db, harness, title='СЕКРЕТ', day=LOCAL.date(), start='13:00', user_id=harness.second_user_id)
        db.commit()
    assert 'ничего не найдено' in text(harness, 'поиск: секрет').text
    assert 'Моя задача' in text(harness, 'поиск: моя').text


def test_group_guard_does_not_read_or_consume_pending_search(harness):
    seed(harness, title='Приватная задача')
    callback(harness, 'search')
    for update in (harness._update('Приватная', chat_id=-100), harness._callback('search', chat_id=-100)):
        message = update.get('message') or update['callback_query']['message']
        message['chat']['type'] = 'supergroup'
        with harness.SessionLocal() as db, patch.object(search, 'collect', side_effect=AssertionError('private data')):
            reply = handle_telegram_update(db, update)
        assert 'личный чат' in reply.text and 'Приватная' not in reply.text
    assert 'Приватная задача' in text(harness, 'Приватная').text


def test_unlinked_relink_and_callbacks_cannot_reuse_another_users_search(harness):
    for n in range(6): seed(harness, title=f'БД {n}')
    reply = text(harness, 'поиск: бд')
    page = more(reply, 'tasks')
    with harness.SessionLocal() as db:
        user = db.get(User, harness.second_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7002, 8002
        db.commit()
    assert 'устарел' in callback(harness, page, telegram_user_id=7002, chat_id=8002).text
    callback(harness, 'search')
    with harness.SessionLocal() as db:
        clear_telegram_link(db.get(User, harness.first_user_id)); db.commit()
    assert 'подключи' in callback(harness, 'search').text
    assert 'подключи' in text(harness, 'поиск: бд').text
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7001, 8001
        user.telegram_linked_at = NOW.replace(tzinfo=None)
        db.commit()
    assert 'устарел' in text(harness, 'бд').text
    assert 'устарел' in callback(harness, page).text


@pytest.mark.parametrize('suffix', ['bad', 'x:tasks:0', 'x:other:0', 'x:tasks:-1', 'x:tasks:999999999999999999999999'])
def test_malformed_callbacks_are_safe(harness, suffix):
    assert 'устарел' in callback(harness, 'search_page:' + suffix).text
