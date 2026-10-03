"""Production contracts; the same concurrency cases run against SQLite and PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from threading import Barrier, Event
from unittest.mock import MagicMock, Mock, patch
import logging
import time as clock

import pytest
from sqlalchemy import inspect, text as sql

from app.core.config import get_settings, settings
from app.core.migrations import MIGRATIONS, run_migrations
from app.models import Note, Task, TelegramState, TelegramUpdate, User
from app.services import telegram_class_reminders as classes, telegram_evening_digest as evening, telegram_weekly_digest as weekly
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, handle_telegram_update
from app.services.telegram_delivery import process_update, retry_pending_replies
from telegram_bot import scheduler
from test_telegram_now import add_lesson
from test_telegram_task_draft import NOW, action, click, frozen_clock, harness, text
from test_telegram_task_actions import press, task_action

SUNDAY = datetime(2026, 10, 4, 18, tzinfo=UTC)


def race(operation):
    barrier = Barrier(2)
    def worker(index):
        barrier.wait(timeout=10)
        return operation(index)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, i) for i in range(2)]
        return [future.result(timeout=40) for future in futures]


def callback(harness, value):
    with harness.SessionLocal() as db:
        return handle_telegram_update(db, harness._callback(value))


def seeded(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_linked_at = NOW.replace(tzinfo=None)
        user.telegram_deadline_reminders_enabled = True
        user.telegram_morning_digest_enabled = True
        user.telegram_morning_digest_time = time(21)
        evening.set_preferences(db, user, enabled=True, hour=21)
        weekly.set_preferences(db, user, enabled=True, day=6, hour=21)
        classes.set_preferences(db, user, enabled=True)
        db.add(Task(user_id=user.id, title='Тест дедлайна', deadline=datetime(2026,10,4,23)))
        add_lesson(db, harness, day=SUNDAY.date(), start='21:15', end='22:45')
        db.commit()


@pytest.mark.parametrize('kind', ['morning','evening','weekly','deadline','class','snooze'])
def test_two_schedulers_no_duplicate(harness, kind, caplog):
    seeded(harness)
    caplog.set_level(logging.WARNING)
    operation = {'morning':scheduler.process_due_digests, 'evening':scheduler.process_evening_digests,
                 'weekly':scheduler.process_weekly_digests, 'deadline':scheduler.process_deadline_reminders,
                 'class':scheduler.process_class_reminders, 'snooze':scheduler.process_class_reminders}[kind]
    current = SUNDAY
    if kind == 'snooze':
        sent = []
        with harness.SessionLocal() as db:
            assert operation(db, now_utc=SUNDAY, send_message=sent.append) == 1
            token = next(b['callback_data'].split(':')[1] for row in sent[0].reply_markup['inline_keyboard'] for b in row if b['callback_data'].startswith('class_snooze:'))
            assert 'Хорошо' in classes.request_snooze(db, db.get(User,harness.first_user_id), token, now_utc=SUNDAY)
            db.commit()
        current += timedelta(minutes=10)
    deliveries = []
    def send(reply):
        clock.sleep(.05)  # Force another worker to contend while delivery is in flight.
        deliveries.append(reply)
    def worker(_):
        with harness.SessionLocal() as db:
            return operation(db, now_utc=current, send_message=send)
    assert sum(race(worker)) == 1
    assert len(deliveries) == 1
    assert 'category=processing' not in caplog.text
    with harness.SessionLocal() as db:
        assert operation(db, now_utc=current, send_message=send) == 0


@pytest.mark.parametrize('kind', ['create','done','reschedule','note_delete','snooze'])
def test_parallel_callbacks_single_mutation(harness, kind, caplog):
    if kind == 'create':
        reply = text(harness, 'купить тетрадь')
        value = action(reply, 'add_task_quick_create')
    elif kind == 'note_delete':
        reply = text(harness, 'заметка: Удаляемая заметка')
        value = next(b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row if b['callback_data'].startswith('note_delete:'))
        reply = callback(harness, value)
        value = next(b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row if b['callback_data'].startswith('note_delete_confirm:'))
    elif kind == 'snooze':
        seeded(harness)
        sent = []
        with harness.SessionLocal() as db:
            scheduler.process_class_reminders(db, now_utc=SUNDAY, send_message=sent.append)
        value = next(b['callback_data'] for row in sent[0].reply_markup['inline_keyboard'] for b in row if b['callback_data'].startswith('class_snooze:'))
    else:
        with harness.SessionLocal() as db:
            db.add(Task(user_id=harness.first_user_id, title='Отчёт', deadline=datetime(2026,10,1,18)))
            db.commit()
        reply = text(harness, '/tasks')
        if kind == 'done':
            value = task_action(reply, 'task_done')
        else:
            reply = press(harness, reply, 'task_reschedule')
            reply = click(harness, reply, 'add_task_reschedule_tomorrow')
            value = action(reply, 'add_task_reschedule_save')
    sent = []
    def worker(index):
        update = harness._callback(value)
        update['update_id'] = 88000 + index
        with harness.SessionLocal() as db:
            process_update(db, update, send_message=sent.append)
    with patch.object(classes, 'datetime', wraps=datetime) as fixed:
        fixed.now.return_value = SUNDAY
        race(worker)
    with harness.SessionLocal() as db:
        assert db.query(TelegramUpdate).filter_by(status='sent').count() == 2
        if kind == 'create':
            assert db.query(Task).count() == 1
        elif kind == 'done':
            assert db.query(Task).one().is_completed
            assert db.get(TelegramState, f'task-rev:{harness.first_user_id}:1').data['version'] == 1
        elif kind == 'reschedule':
            assert db.query(Task).one().deadline == datetime(2026,10,1,18)
            assert db.get(TelegramState, f'task-rev:{harness.first_user_id}:1').data['version'] == 1
        elif kind == 'note_delete':
            assert db.query(Note).count() == 0
        else:
            rows = db.query(TelegramState).filter(TelegramState.key.startswith('class-event:')).all()
            assert len(rows) == 1 and rows[0].data['snooze_status'] == 'pending'
    assert 'processing_failed' not in caplog.text


def test_outbox_does_not_deliver_from_previous_link(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_linked_at = NOW.replace(tzinfo=None)
        db.commit()
        update = {**harness._update('/tasks'), 'update_id':9999}
        with pytest.raises(TelegramAPIError):
            process_update(db, update, send_message=Mock(side_effect=TelegramAPIError(category='network')))
        user.telegram_linked_at += timedelta(seconds=1)  # Same account/IDs, new binding.
        record = db.get(TelegramUpdate,9999)
        record.available_at = NOW.replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
        send = Mock()
        retry_pending_replies(db, send_message=send)
        send.assert_not_called()
        assert db.get(TelegramUpdate,9999).status == 'cancelled'


def test_scheduler_reconnects_after_session_creation_failure():
    stop = Event()
    factory = Mock(side_effect=[RuntimeError('private DB credentials'), MagicMock()])
    def pause(_):
        stop.set()
    with patch.object(scheduler, 'scheduler_tick') as tick:
        scheduler.run_scheduler(session_factory=factory, stop_event=Mock(is_set=Mock(side_effect=[False,False,True]), wait=pause))
    assert factory.call_count == 2 and tick.call_count == 1


def test_scheduler_job_failure_does_not_skip_other_jobs(harness):
    with harness.SessionLocal() as db, patch.object(scheduler,'retry_pending_replies',side_effect=RuntimeError('private')), patch.object(scheduler,'process_due_digests'), patch.object(scheduler,'process_deadline_reminders'), patch.object(scheduler,'process_class_reminders'), patch.object(scheduler,'process_evening_digests'), patch.object(scheduler,'process_weekly_digests') as last:
        scheduler.scheduler_tick(db)
        last.assert_called_once()
        assert db.get(TelegramState,'scheduler-heartbeat').data['state'] == 'degraded'


def production_env(monkeypatch):
    for name in ['TELEGRAM_USE_WEBHOOK','PUBLIC_BASE_URL','TELEGRAM_WEBHOOK_BASE_URL']:
        monkeypatch.delenv(name, raising=False)
    for name,value in {'APP_ENV':'production','TESTING':'false','DISABLE_TELEGRAM':'false',
        'SECRET_KEY':'test-only-persistent-secret-key-123456789', 'COOKIE_SECURE':'true',
        'DATABASE_URL':'postgresql+psycopg://test@localhost/sa_telegram_test_config',
        'TELEGRAM_BOT_TOKEN':'fake-token','TELEGRAM_BOT_USERNAME':'test_bot',
        'TELEGRAM_WEBHOOK_SECRET':'test-only-hook-secret-123456789012345',
        'PUBLIC_ORIGIN':'https://example.invalid', 'TELEGRAM_MODE':'webhook'}.items():
        monkeypatch.setenv(name,value)


@pytest.mark.parametrize('name,value,reason', [
    ('DATABASE_URL','sqlite:////tmp/sa-prod-config-only.db','PostgreSQL'),
    ('TELEGRAM_MODE','polling','webhook'), ('SECRET_KEY','','SECRET_KEY'),
    ('TELEGRAM_WEBHOOK_SECRET','short','TELEGRAM_WEBHOOK_SECRET'),
    ('TELEGRAM_BOT_USERNAME','','TELEGRAM_BOT_USERNAME'),
    ('PUBLIC_ORIGIN','https://name:password@example.invalid','origin'),
    ('PUBLIC_ORIGIN','https://example.invalid?secret=private','origin'),
])
def test_production_rejects_unsafe_configuration(monkeypatch,name,value,reason):
    production_env(monkeypatch)
    monkeypatch.setenv(name,value)
    with pytest.raises(RuntimeError, match=reason): get_settings()


def test_production_settings_valid_and_repr_hides_secrets(monkeypatch):
    production_env(monkeypatch)
    configured=get_settings()
    assert configured.telegram_use_webhook
    assert configured.secret_key not in repr(configured)
    assert configured.telegram_bot_token not in repr(configured)
    assert configured.database_url not in repr(configured)


def test_commands_cli_uses_single_source():
    from telegram_bot import set_commands
    from app.services import telegram_bot
    configured=replace(settings, telegram_bot_token='fake')
    with patch.object(set_commands,'settings',configured), patch.object(telegram_bot,'call_telegram_api') as api:
        assert set_commands.main() == 0
    assert api.call_args.args == ('setMyCommands', {'commands':BOT_COMMANDS})
    assert [c['command'] for c in BOT_COMMANDS] == ['start','today','tomorrow','week','tasks','add_task']


def test_migrations_repeat_and_tables(harness):
    run_migrations(harness.engine)
    run_migrations(harness.engine)
    with harness.engine.connect() as connection:
        assert set(connection.execute(sql('SELECT version FROM schema_migrations')).scalars()) == {m.version for m in MIGRATIONS}
    tables=set(inspect(harness.engine).get_table_names())
    assert {'telegram_state','telegram_updates','workspaces','workspace_devices','device_link_sessions','telegram_deadline_reminder_logs'} <= tables


def test_scheduler_and_settings_callback_share_lock_order(harness, caplog):
    seeded(harness)
    started = Event()
    def worker():
        started.set()
        with harness.SessionLocal() as db:
            return scheduler.process_weekly_digests(db, now_utc=SUNDAY, send_message=lambda reply: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with harness.SessionLocal() as db:
            user = db.get(User,harness.first_user_id)
            db.refresh(user,with_for_update=True)
            future = pool.submit(worker)
            assert started.wait(5)
            clock.sleep(.1)
            weekly.set_preferences(db,user,enabled=True)
            db.commit()
        assert future.result(timeout=20) == 1
    assert 'category=processing' not in caplog.text


def test_clean_migrations_are_serialized(harness, tmp_path):
    from uuid import uuid4
    from sqlalchemy import create_engine
    if harness.engine.dialect.name == 'postgresql':
        schema = 'telegram_migration_test_' + uuid4().hex
        with harness.engine.begin() as connection:
            connection.execute(sql(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(harness.engine.url, hide_parameters=True,
                               connect_args={'options':f'-c search_path={schema} -c lock_timeout=10000'})
        try:
            race(lambda _: run_migrations(engine))
            with engine.connect() as connection:
                assert len(connection.execute(sql('SELECT version FROM schema_migrations')).all()) == len(MIGRATIONS)
            assert 'telegram_updates' in inspect(engine).get_table_names()
        finally:
            engine.dispose()
            with harness.engine.begin() as connection:
                connection.execute(sql(f'DROP SCHEMA "{schema}" CASCADE'))
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'clean.db'))
        try:
            run_migrations(engine)
            run_migrations(engine)
            assert 'telegram_updates' in inspect(engine).get_table_names()
        finally:
            engine.dispose()


def test_clean_workspace_http_and_telegram_smoke(harness):
    from app.core.rate_limit import auth_rate_limiter
    from app.services.telegram_bot import clear_telegram_link
    from app.web.routes import telegram as webhook
    auth_rate_limiter.clear()
    # The harness creates fixture users; use a fresh HTTP workspace for this smoke.
    with harness.SessionLocal() as db:
        clear_telegram_link(db.get(User,harness.first_user_id)); db.commit()
    csrf = harness._csrf(harness.client.get('/').text)
    assert harness.client.post('/start',data={'display_name':'Production smoke','csrf_token':csrf}).status_code == 200
    csrf = harness._csrf(harness.client.get('/profile').text)
    assert harness.client.post('/profile/telegram/link-code',data={'csrf_token':csrf}).status_code == 200
    with harness.SessionLocal() as db:
        user = db.query(User).filter_by(is_local_profile=True).one()
        code, uid = user.telegram_link_code, user.id
        assert user.workspace is not None
    configured=replace(settings,telegram_bot_token='fake',telegram_use_webhook=True,telegram_webhook_secret='test-header')
    sent=[]
    def deliver(update):
        response=harness.client.post(settings.telegram_webhook_path,json={**update,'update_id':91000+len(sent)},headers={'X-Telegram-Bot-Api-Secret-Token':'test-header'})
        assert response.status_code == 200
        return sent[-1]
    with patch.object(webhook,'settings',configured),patch.object(webhook,'send_telegram_message',side_effect=sent.append):
        for command in [f'/link {code}','/start','/today','/tasks']:
            deliver(harness._update(command))
        offer=deliver(harness._update('сдать практику завтра в 18'))
        deliver(harness._callback(action(offer,'add_task_quick_create')))
        deliver(harness._update('заметка: Практика SQL'))
        assert 'Практик' in deliver(harness._update('поиск: практик')).text
    with harness.SessionLocal() as db:
        assert db.query(Task).filter_by(user_id=uid).count() == 1
        assert db.query(Note).filter_by(user_id=uid).count() == 1
        user=db.get(User,uid)
        user.telegram_deadline_reminders_enabled=True
        db.commit()
        assert scheduler.process_deadline_reminders(db,now_utc=NOW,send_message=sent.append) == 0


def test_diagnostics_report_local_readiness_without_network(harness):
    from telegram_bot import diagnose
    run_migrations(harness.engine)
    with patch.object(diagnose,'engine',harness.engine), patch.object(diagnose,'SessionLocal',harness.SessionLocal), patch.object(diagnose,'call_telegram_api') as api:
        report=diagnose.report()
    api.assert_not_called()
    assert report['database_accessible'] and report['missing_tables'] == []
    assert report['missing_migrations'] == []
    assert report['pending_replies'] == report['failed_replies'] == 0
    assert report['pending_updates'] is None
    assert report['production_safe'] is False
    assert 'scheduler_not_healthy' in report['production_readiness_blockers']
    assert report['database_kind'] == harness.engine.dialect.name
    assert report['database_shared_across_services'] == ('must_verify_in_hosting' if harness.engine.dialect.name == 'postgresql' else False)


def test_unknown_notification_failures_bounded_and_redacted(harness, caplog):
    from app.services.telegram_state import state_row
    from app.services.telegram_bot import TelegramReply
    send=Mock(side_effect=RuntimeError('do-not-log-private-token-or-message'))
    with harness.SessionLocal() as db:
        user=db.get(User,harness.first_user_id)
        for attempt in range(6):
            row=state_row(db,'test-retry')
            row.expires_at=NOW.replace(tzinfo=None)-timedelta(seconds=1)
            scheduler._send_notification(db,row,'delivery',TelegramReply(chat_id=8001,text='private'),send,user,now=NOW.replace(tzinfo=None))
        assert row.data['terminal'] and row.data['attempts'] == 5
    assert send.call_count == 5
    assert 'do-not-log-private' not in caplog.text


def test_production_polling_and_webhook_deletion_never_touch_network():
    from telegram_bot import polling, set_webhook
    configured=replace(settings,app_env='production',telegram_bot_token='fake',telegram_use_webhook=False)
    with patch.object(polling,'settings',configured),patch.object(polling,'call_telegram_api') as api:
        assert polling.main() == 1
        api.assert_not_called()
    with patch.object(set_webhook,'settings',configured),patch.object(set_webhook,'delete_telegram_webhook') as delete:
        assert set_webhook.main(['--delete-for-polling']) == 1
        delete.assert_not_called()
