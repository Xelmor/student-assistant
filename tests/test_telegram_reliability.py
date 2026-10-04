from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

import test_telegram_bot as harness_module
from app.models import User
from app.services.telegram_bot import handle_telegram_update
from telegram_bot import polling


@pytest.fixture
def harness():
    case = harness_module.TelegramBotTests()
    case._testMethodName = 'reliability'
    case.setUp()
    yield case
    case.tearDown()


def test_group_cannot_read_tasks_or_replace_private_chat(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7001, 8001
        db.commit()
        update = harness._update('/tasks', chat_id=-123)
        update['message']['chat']['type'] = 'supergroup'
        reply = handle_telegram_update(db, update)
        db.refresh(user)
        assert user.telegram_chat_id == 8001
        assert reply is None or 'личн' in reply.text.lower()


def test_failed_update_does_not_advance_polling_offset():
    seen = []
    def processor(update):
        seen.append(update['update_id'])
        if update['update_id'] == 10:
            raise RuntimeError('simulated')
    assert polling.process_updates([{'update_id': 10}, {'update_id': 11}], 10, processor=processor) == 10
    assert seen == [10]

from datetime import UTC, datetime, timedelta, time
import io
import json
import re
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings
from app.core.time import current_time
from app.core.rate_limit import auth_rate_limiter
from app.models import Task, TelegramUpdate, TelegramState, TelegramDeadlineReminderLog, Subject, ScheduleItem, AcademicEvent
from app.services.telegram_bot import TelegramAPIError, TelegramReply, generate_link_code, call_telegram_api, send_telegram_message
from app.services.telegram_delivery import process_update, retry_pending_replies
from app.services.telegram_state import utcnow
from telegram_bot import scheduler


def linked(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_user_id, user.telegram_chat_id = 7001, 8001
        db.commit()


def deliver(harness, update, update_id, send=lambda reply: None):
    with harness.SessionLocal() as db:
        process_update(db, {**update, 'update_id': update_id}, send_message=send)


def test_passwordless_http_link_to_send_message_and_real_tasks(harness):
    auth_rate_limiter.clear()
    csrf = harness._csrf(harness.client.get('/').text)
    response = harness.client.post('/start', data={'display_name': 'Моё пространство', 'csrf_token': csrf})
    assert response.status_code == 200
    csrf = harness._csrf(harness.client.get('/profile').text)
    response = harness.client.post('/profile/telegram/link-code', data={'csrf_token': csrf})
    assert response.status_code == 200
    with harness.SessionLocal() as db:
        user = db.query(User).filter_by(is_local_profile=True).one()
        user_id, code = user.id, user.telegram_link_code
        assert user.workspace is not None
        db.add(Task(user_id=user_id, title='Данные пространства <математика>'))
        db.commit()
    api_requests = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"ok":true,"result":{}}'
    def fake_urlopen(request, timeout):
        api_requests.append((request.full_url.rsplit('/', 1)[-1], json.loads(request.data)))
        return Response()
    configured = replace(settings, telegram_bot_token='isolated-token', telegram_use_webhook=True, telegram_webhook_secret='isolated-secret')
    with patch('app.web.routes.telegram.settings', configured), patch('app.services.telegram_bot.settings', configured), patch('app.services.telegram_bot.urlopen', side_effect=fake_urlopen):
        response = harness.client.post(settings.telegram_webhook_path, headers={'X-Telegram-Bot-Api-Secret-Token': 'isolated-secret'}, json={**harness._update(f'/start link_{code}'), 'update_id': 1})
        assert response.status_code == 200
        response = harness.client.post(settings.telegram_webhook_path, headers={'X-Telegram-Bot-Api-Secret-Token': 'isolated-secret'}, json={**harness._update('/tasks'), 'update_id': 2})
        assert response.status_code == 200
    outgoing = [payload for method, payload in api_requests if method == 'sendMessage']
    assert len(outgoing) == 2
    assert 'Моё пространство' in outgoing[0]['text']
    assert 'Данные пространства &lt;математика&gt;' in outgoing[1]['text']
    assert harness.client.get('/profile/telegram/status').json()['state'] == 'linked'
    with harness.SessionLocal() as db:
        assert db.query(User).count() == 3  # Two fixture users + existing passwordless space only.
        assert db.get(User, user_id).telegram_link_code is None


@pytest.mark.parametrize('command', ['/add_task Новая задача', '/digest_on'])
def test_lost_reply_does_not_repeat_committed_operation(harness, command):
    linked(harness)
    update = harness._update(command)
    with pytest.raises(TelegramAPIError):
        deliver(harness, update, 1, Mock(side_effect=TelegramAPIError(category='network')))
    with harness.SessionLocal() as db:
        record = db.get(TelegramUpdate, 1)
        record.available_at = utcnow() - timedelta(seconds=1)
        db.commit()
    sent = []
    deliver(harness, update, 1, sent.append)
    deliver(harness, update, 1, sent.append)
    assert len(sent) == 1
    with harness.SessionLocal() as db:
        assert db.query(Task).count() == (1 if command.startswith('/add') else 0)
        assert db.get(TelegramUpdate, 1).status == 'sent'
        assert db.get(TelegramUpdate, 1).reply is None


def test_duplicate_toggle_and_link_keep_original_result(harness):
    with harness.SessionLocal() as db:
        code = generate_link_code(db, db.get(User, harness.first_user_id))
    sent = []
    deliver(harness, harness._update(f'/link {code}'), 1, sent.append)
    deliver(harness, harness._update(f'/link {code}'), 1, sent.append)
    deliver(harness, harness._callback('digest_toggle'), 2, sent.append)
    deliver(harness, harness._callback('digest_toggle'), 2, sent.append)
    assert len(sent) == 2
    with harness.SessionLocal() as db:
        assert db.get(User, harness.first_user_id).telegram_morning_digest_enabled


def test_rollback_after_mutation_keeps_update_retryable(harness):
    linked(harness)
    from app.services import telegram_delivery
    actual = telegram_delivery.handle_telegram_update
    def crash(db, update):
        actual(db, update)
        raise RuntimeError('crash before transaction commit')
    with patch.object(telegram_delivery, 'handle_telegram_update', side_effect=crash), pytest.raises(RuntimeError):
        deliver(harness, harness._update('/add_task Atomic'), 10)
    with harness.SessionLocal() as db:
        assert db.query(Task).count() == 0
        assert db.get(TelegramUpdate, 10) is None
    deliver(harness, harness._update('/add_task Atomic'), 10)
    with harness.SessionLocal() as db:
        assert db.query(Task).count() == 1


def test_concurrent_same_update_changes_database_once(harness):
    linked(harness)
    sent = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(deliver, harness, harness._update('/add_task Concurrent'), 20, sent.append) for _ in range(2)]
        for future in futures: future.result()
    with harness.SessionLocal() as db:
        assert db.query(Task).count() == 1
    assert len(sent) == 1


def test_two_people_cannot_consume_same_code(harness):
    with harness.SessionLocal() as db:
        code = generate_link_code(db, db.get(User, harness.first_user_id))
    sent = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(deliver, harness, harness._update(f'/link {code}', telegram_user_id=i, chat_id=i), i, sent.append) for i in (101, 102)]
        for future in futures: future.result()
    assert sum('Telegram подключён!' in reply.text for reply in sent) == 1


def test_persistent_dialog_and_stale_state(harness):
    linked(harness)
    deliver(harness, harness._update('/add_task'), 1)
    deliver(harness, harness._update('Сохранённое название'), 2)
    with harness.SessionLocal() as db:
        row = db.get(TelegramState, 'dialog:7001')
        assert row.data['title'] == 'Сохранённое название'
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    sent = []
    deliver(harness, harness._callback('add_task_confirm_create'), 3, sent.append)
    assert 'устарело' in sent[0].text
    with harness.SessionLocal() as db:
        assert db.query(Task).count() == 0


def test_done_number_uses_displayed_id_after_sort_changes(harness):
    linked(harness)
    with harness.SessionLocal() as db:
        task = Task(user_id=harness.first_user_id, title='Показанная', deadline=current_time())
        db.add(task); db.commit(); first_id = task.id
    deliver(harness, harness._update('/tasks'), 1)
    with harness.SessionLocal() as db:
        task = Task(user_id=harness.first_user_id, title='Новая первая', deadline=current_time() - timedelta(days=1))
        db.add(task); db.commit(); other_id = task.id
    deliver(harness, harness._update('/done 1'), 2)
    with harness.SessionLocal() as db:
        assert db.get(Task, first_id).is_completed
        assert not db.get(Task, other_id).is_completed


@pytest.mark.parametrize('action', ['tasks', 'today', 'tomorrow', 'week', 'notifications', 'digest_test', 'done_task:1', 'unlink_confirm', 'digest_toggle'])
def test_group_callbacks_do_not_read_or_modify(harness, action):
    linked(harness)
    update = harness._callback(action, chat_id=-5)
    update['callback_query']['message']['chat']['type'] = 'group'
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, update)
        user = db.get(User, harness.first_user_id)
        assert user.telegram_chat_id == 8001
        assert not user.telegram_morning_digest_enabled
        assert reply.text == 'Открой личный чат с ботом.'


@pytest.mark.parametrize('status,category', [(401, 'invalid_token'), (403, 'blocked'), (409, 'receiver_conflict'), (429, 'rate_limit'), (500, 'temporary'), (400, 'chat_not_found')])
def test_api_errors_classified_without_credentials(status, category):
    error = HTTPError('https://example.invalid/botPRIVATE/sendMessage', status, 'SECRET', {}, io.BytesIO(json.dumps({'ok': False, 'description': 'chat not found SECRET', 'parameters': {'retry_after': 17}}).encode()))
    with patch('app.services.telegram_bot.settings', replace(settings, telegram_bot_token='PRIVATE')), patch('app.services.telegram_bot.urlopen', side_effect=error), pytest.raises(TelegramAPIError) as caught:
        call_telegram_api('sendMessage', {})
    assert caught.value.category == category
    assert caught.value.retry_after == 17
    assert 'PRIVATE' not in str(caught.value)
    assert 'SECRET' not in str(caught.value)
    assert caught.value.__suppress_context__


def test_auxiliary_api_failure_still_sends_main_reply():
    def api(method, payload, **kwargs):
        if method != 'sendMessage': raise TelegramAPIError(category='temporary')
        return {'ok': True}
    with patch('app.services.telegram_bot.call_telegram_api', side_effect=api) as mock:
        send_telegram_message(TelegramReply(chat_id=1, text='Ответ', chat_action='typing', callback_query_id='test'))
    assert mock.call_args.args[0] == 'sendMessage'


def test_long_escaped_message_is_split_safely():
    with patch('app.services.telegram_bot.call_telegram_api', return_value={'ok': True}) as mock:
        send_telegram_message(TelegramReply(chat_id=1, text='<b>' + '🙂 &lt;&amp;&gt; ' * 1000 + '</b>'))
    assert len(mock.call_args_list) > 1
    for call in mock.call_args_list:
        payload = call.args[1]
        assert len(payload['text'].encode('utf-16-le')) // 2 < 4096
        assert 'parse_mode' not in payload


@pytest.mark.parametrize('mode,token,header,expected', [(True, 'fake', 'wrong', 403), (False, 'fake', 'isolated-secret', 503), (True, '', 'isolated-secret', 503), (True, 'fake', 'isolated-secret', 200)])
def test_webhook_header_transport(harness, mode, token, header, expected):
    configured = replace(settings, telegram_use_webhook=mode, telegram_bot_token=token, telegram_webhook_secret='isolated-secret')
    with patch('app.web.routes.telegram.settings', configured), patch('app.web.routes.telegram.send_telegram_message'):
        response = harness.client.post(settings.telegram_webhook_path, json={**harness._update('/start'), 'update_id': 1}, headers={'X-Telegram-Bot-Api-Secret-Token': header})
    assert response.status_code == expected


def test_webhook_stream_limit_without_trusting_content_length(harness):
    configured = replace(settings, telegram_use_webhook=True, telegram_bot_token='fake', telegram_webhook_secret='isolated-secret')
    with patch('app.web.routes.telegram.settings', configured):
        response = harness.client.post(settings.telegram_webhook_path, content=b' ' * 1_000_001, headers={'X-Telegram-Bot-Api-Secret-Token': 'isolated-secret', 'Content-Length': '1'})
    assert response.status_code == 413


def test_webhook_does_not_acknowledge_lost_response(harness):
    configured = replace(settings, telegram_use_webhook=True, telegram_bot_token='fake', telegram_webhook_secret='isolated-secret')
    with patch('app.web.routes.telegram.settings', configured), patch('app.web.routes.telegram.send_telegram_message', side_effect=TelegramAPIError(category='network')):
        response = harness.client.post(settings.telegram_webhook_path, json={**harness._update('/start'), 'update_id': 1}, headers={'X-Telegram-Bot-Api-Secret-Token': 'isolated-secret'})
    assert response.status_code == 503
    with harness.SessionLocal() as db:
        assert db.get(TelegramUpdate, 1).status == 'pending'


def test_profile_status_requires_owner_and_test_is_csrf_rate_limited(harness):
    assert harness.client.get('/profile/telegram/status').status_code == 401
    harness._login(); linked(harness)
    csrf = harness._csrf(harness.client.get('/profile').text)
    assert harness.client.post('/profile/telegram/digest-test').status_code == 403
    with patch('app.web.routes.profile.send_telegram_message') as send:
        for _ in range(4):
            response = harness.client.post('/profile/telegram/digest-test', data={'csrf_token': csrf}, follow_redirects=False)
        assert send.call_count == 3
        assert 'rate-limited' in response.headers['location']
        assert all(call.args[0].chat_id == 8001 for call in send.call_args_list)


def test_notification_success_logged_only_after_send_and_restart(harness):
    linked(harness)
    instant = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_enabled = True
        user.telegram_morning_digest_time = time(8)
        db.commit()
    sent = []
    def sender(reply):
        with harness.SessionLocal() as observer:
            assert observer.get(User, harness.first_user_id).telegram_morning_digest_last_sent_date is None
        sent.append(reply)
    with harness.SessionLocal() as db:
        assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 1
    with harness.SessionLocal() as db:
        assert scheduler.process_due_digests(db, now_utc=instant, send_message=sent.append) == 0
    assert len(sent) == 1


def test_two_schedulers_send_one_digest(harness):
    linked(harness)
    instant = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_enabled = True
        db.commit()
    sent = []
    def run():
        with harness.SessionLocal() as db:
            return scheduler.process_due_digests(db, now_utc=instant, send_message=sent.append)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: run(), range(2))) == 1
    assert len(sent) == 1


def test_scheduler_blocked_has_bounded_retry_and_missed_digest_expires(harness):
    linked(harness)
    instant = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_enabled = True
        db.commit()
        sender = Mock(side_effect=TelegramAPIError(category='blocked'))
        assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 0
        assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 0
        assert sender.call_count == 1
        assert user.telegram_morning_digest_last_sent_date is None
        assert not scheduler.is_digest_due(user, instant + timedelta(hours=5))


def test_pending_reply_cancelled_after_unlink(harness):
    linked(harness)
    with pytest.raises(TelegramAPIError):
        deliver(harness, harness._update('/tasks'), 1, Mock(side_effect=TelegramAPIError(category='network')))
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_user_id, user.telegram_chat_id = None, None
        db.get(TelegramUpdate, 1).available_at = utcnow() - timedelta(seconds=1)
        db.commit()
        sender = Mock()
        retry_pending_replies(db, send_message=sender)
        sender.assert_not_called()
        assert db.get(TelegramUpdate, 1).status == 'cancelled'


def test_link_bruteforce_limited_and_new_code_revokes_previous(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        old = generate_link_code(db, user)
        new = generate_link_code(db, user)
        assert old != new
        assert 'истёк' in handle_telegram_update(db, harness._update(f'/link {old}')).text
        for _ in range(4):
            handle_telegram_update(db, harness._update('/link WRONGX'))
        assert 'много попыток' in handle_telegram_update(db, harness._update(f'/link {new}')).text
        assert user.telegram_user_id is None


def test_telegram_task_is_same_record_on_website(harness):
    harness._login(); linked(harness)
    deliver(harness, harness._update('/add_task Синхронизация сайта'), 1)
    assert 'Синхронизация сайта' in harness.client.get('/tasks').text
    deliver(harness, harness._update('/tasks'), 2)
    deliver(harness, harness._update('/done 1'), 3)
    with harness.SessionLocal() as db:
        task = db.query(Task).one()
        assert task.is_completed
        task_id = task.id
    csrf = harness._csrf(harness.client.get('/tasks').text)
    assert harness.client.post(f'/tasks/toggle/{task_id}', data={'csrf_token': csrf}).status_code == 200
    sent = []
    deliver(harness, harness._update('/tasks'), 4, sent.append)
    assert 'Синхронизация сайта' in sent[0].text


def test_old_dialog_button_cannot_mutate_new_dialog(harness):
    linked(harness)
    sent = []
    deliver(harness, harness._update('/add_task'), 1)
    deliver(harness, harness._update('Первое название'), 2, sent.append)
    old_action = sent[0].reply_markup['inline_keyboard'][0][0]['callback_data']
    assert len(old_action.encode()) <= 64
    deliver(harness, harness._update('/cancel'), 3)
    deliver(harness, harness._update('/add_task'), 4)
    sent.clear()
    deliver(harness, harness._callback(old_action), 5, sent.append)
    assert 'устарело' in sent[0].text
    with harness.SessionLocal() as db:
        assert db.get(TelegramState, 'dialog:7001').data['step'] == 'add_task_waiting_title'


def test_timezone_changes_today_at_midnight(harness):
    linked(harness)
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        db.add(Task(user_id=user.id, title='Задача нового дня', deadline=datetime(2026, 9, 30, 18)))
        db.commit()
    from app.services.telegram_digest import digest_local_datetime
    instant = datetime(2026, 9, 29, 15, tzinfo=UTC)
    with patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, instant)):
        sent = []
        deliver(harness, harness._update('/today'), 1, sent.append)
    assert 'Задача нового дня' in sent[0].text


def test_cancellation_and_summer_rules_match_calendar(harness):
    from app.services.telegram_bot import _day_plan
    from app.services.telegram_digest import build_morning_digest_message
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        subject = Subject(user_id=user.id, name='Пара')
        db.add(subject); db.flush()
        day = datetime(2026, 9, 29).date()
        db.add(ScheduleItem(user_id=user.id, subject_id=subject.id, weekday=day.weekday(), start_time=time(9), end_time=time(10)))
        db.add(AcademicEvent(user_id=user.id, title='Пары отменены', event_type='day_override', event_date=day))
        db.commit()
        lessons, tasks, events = _day_plan(db, user, day)
        assert lessons == []
        assert events[0].title == 'Пары отменены'
        assert 'Ближайшая пара' not in build_morning_digest_message(db, user, target_date=day)
        summer_day = datetime(2026, 6, 30).date()
        assert _day_plan(db, user, summer_day)[0] == []


def test_diagnostic_is_read_only_and_network_opt_in(harness):
    from telegram_bot import diagnose
    configured = replace(settings, telegram_bot_token='PRIVATE', telegram_bot_username='expected_bot', telegram_webhook_secret='secret', public_base_url='https://example.invalid', telegram_webhook_base_url='', telegram_bot_api_base_url='')
    with patch.object(diagnose, 'engine', harness.engine), patch.object(diagnose, 'SessionLocal', harness.SessionLocal), patch.object(diagnose, 'settings', configured), patch('telegram_bot.set_webhook.settings', configured), patch.object(diagnose, 'call_telegram_api') as api:
        report = diagnose.report()
        api.assert_not_called()
        assert report['scheduler'] == 'not_observed'
        api.side_effect = [{'result': {'username': 'different_bot'}}, {'result': {'url': 'https://secret.invalid/secret', 'pending_update_count': 8, 'last_error_message': 'HTTP response at PRIVATE'}}]
        report = diagnose.report(network=True)
    assert [call.args[0] for call in api.call_args_list] == ['getMe', 'getWebhookInfo']
    assert not report['username_matches']
    assert not report['webhook_matches']
    assert report['pending_update_count'] == 8
    assert 'PRIVATE' not in json.dumps(report)
    assert 'secret.invalid' not in json.dumps(report)


def test_polling_conflict_does_not_switch_transport():
    configured = replace(settings, telegram_use_webhook=False, telegram_bot_token='fake')
    with patch('telegram_bot.polling.settings', configured), patch('telegram_bot.polling.call_telegram_api', return_value={'result': {'url': 'https://example.invalid'}}) as api, patch('telegram_bot.polling.run_polling') as run:
        assert polling.main() == 1
    assert api.call_args.args[0] == 'getWebhookInfo'
    run.assert_not_called()


def test_rate_limit_obeys_retry_after_and_stops_after_five_attempts(harness):
    sender = Mock(side_effect=TelegramAPIError(category='rate_limit', retry_after=77))
    update = harness._update('/start')
    for attempt in range(5):
        before = utcnow()
        with pytest.raises(TelegramAPIError):
            deliver(harness, update, 1, sender)
        with harness.SessionLocal() as db:
            record = db.get(TelegramUpdate, 1)
            assert record.available_at >= before + timedelta(seconds=76)
            record.available_at = utcnow() - timedelta(seconds=1)
            db.commit()
    deliver(harness, update, 1, sender)
    assert sender.call_count == 5
    with harness.SessionLocal() as db:
        assert db.get(TelegramUpdate, 1).status == 'failed'


def test_heartbeat_expires_and_migrations_are_nondestructive(harness):
    from app.core.migrations import run_migrations
    with harness.SessionLocal() as db:
        db.add(Task(user_id=harness.first_user_id, title='Сохранить при миграции'))
        db.commit()
    run_migrations(harness.engine)
    run_migrations(harness.engine)
    with harness.SessionLocal() as db:
        assert db.query(Task).one().title == 'Сохранить при миграции'
        with patch('telegram_bot.scheduler.retry_pending_replies'), patch('telegram_bot.scheduler.process_due_digests'), patch('telegram_bot.scheduler.process_deadline_reminders'):
            scheduler.scheduler_tick(db)
        assert db.get(TelegramState, 'scheduler-heartbeat').expires_at > utcnow()
        assert db.get(TelegramState, 'scheduler-heartbeat').data['state'] == 'completed'


def test_logs_and_exception_format_do_not_expose_api_secret():
    import traceback
    from app.core.telegram_logging import TelegramLogFilter
    import logging
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, 'POST /telegram/webhook/PRIVATE', (), None)
    TelegramLogFilter().filter(record)
    assert 'PRIVATE' not in record.getMessage()
    with patch('app.services.telegram_bot.settings', replace(settings, telegram_bot_token='PRIVATE')), patch('app.services.telegram_bot.urlopen', side_effect=URLError('https://api.telegram.org/botPRIVATE/sendMessage')):
        try:
            call_telegram_api('sendMessage', {})
        except TelegramAPIError as error:
            formatted = ''.join(traceback.format_exception(error))
    assert 'botPRIVATE' not in formatted


@pytest.mark.parametrize('body,status', [(b'not-json', 400), (b'[]', 400), (b'{"update_id":true}', 400), (b'{"update_id":1,"message":null}', 200)])
def test_malformed_or_unsupported_webhook_is_predictable(harness, body, status):
    configured = replace(settings, telegram_use_webhook=True, telegram_bot_token='fake', telegram_webhook_secret='isolated-secret')
    with patch('app.web.routes.telegram.settings', configured), patch('app.web.routes.telegram.send_telegram_message') as send:
        response = harness.client.post(settings.telegram_webhook_path, content=body, headers={'X-Telegram-Bot-Api-Secret-Token': 'isolated-secret'})
    assert response.status_code == status
    send.assert_not_called()


def test_notification_temporary_failure_waits_then_recovers(harness):
    linked(harness)
    instant = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    now = utcnow()
    sender = Mock(side_effect=[TelegramAPIError(category='temporary'), None])
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_enabled = True
        db.commit()
        with patch('telegram_bot.scheduler.utcnow', return_value=now):
            assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 0
            assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 0
        assert sender.call_count == 1
        with patch('telegram_bot.scheduler.utcnow', return_value=now + timedelta(seconds=61)):
            assert scheduler.process_due_digests(db, now_utc=instant, send_message=sender) == 1
        assert sender.call_count == 2


def test_invalid_sender_is_ignored_without_poisoning_update(harness):
    update = harness._update('/start')
    update['message']['from']['id'] = {'not': 'an integer'}
    sender = Mock()
    deliver(harness, update, 99, sender)
    sender.assert_not_called()
    with harness.SessionLocal() as db:
        assert db.get(TelegramUpdate, 99).status == 'sent'


def test_failed_tasks_reply_does_not_replace_last_visible_numbering(harness):
    linked(harness)
    with harness.SessionLocal() as db:
        task = Task(user_id=harness.first_user_id, title='Увиденная', deadline=current_time())
        db.add(task); db.commit(); first_id = task.id
    deliver(harness, harness._update('/tasks'), 1)
    with harness.SessionLocal() as db:
        db.add(Task(user_id=harness.first_user_id, title='Не увиденная', deadline=current_time() - timedelta(days=1)))
        db.commit()
    with pytest.raises(TelegramAPIError):
        deliver(harness, harness._update('/tasks'), 2, Mock(side_effect=TelegramAPIError(category='network')))
    deliver(harness, harness._update('/done 1'), 3)
    with harness.SessionLocal() as db:
        assert db.get(Task, first_id).is_completed
        assert not db.query(Task).filter_by(title='Не увиденная').one().is_completed
