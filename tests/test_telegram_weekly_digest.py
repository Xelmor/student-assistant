"""Calendar-week views and delivery against the real DB, fixed time, fake transport."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
import subprocess
import sys
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from app.models import AcademicEvent, Task, TelegramState, User
from app.services import telegram_weekly_digest as weekly
from app.services.telegram_bot import BOT_COMMANDS, TelegramAPIError, clear_telegram_link, handle_telegram_update
from app.services.telegram_digest import digest_local_datetime
from telegram_bot import scheduler
from test_telegram_now import DAY, add_lesson, harness

NOW = datetime(2026, 9, 29, 9, tzinfo=UTC)  # Tue 12:00 Moscow
MONDAY = date(2026, 9, 28)
NEXT = date(2026, 10, 5)
DUE = datetime(2026, 10, 4, 16, tzinfo=UTC)  # Sunday 19:00 Moscow


def user(db, harness):
    return db.get(User, harness.first_user_id)


def task(db, harness, title='Задача', **fields):
    value = Task(user_id=harness.first_user_id, title=title, **fields)
    db.add(value)
    db.commit()
    return value


def callback(harness, action, now=NOW, **kwargs):
    with harness.SessionLocal() as db, patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda owner: digest_local_datetime(owner, now)):
        return handle_telegram_update(db, harness._callback(action, **kwargs))


def enable(harness, **kwargs):
    with harness.SessionLocal() as db:
        weekly.set_preferences(db, user(db, harness), enabled=True, **kwargs)
        db.commit()


def tick(harness, now=DUE, send=None):
    with harness.SessionLocal() as db:
        return scheduler.process_weekly_digests(db, now_utc=now, send_message=send if send is not None else lambda _: None)


def actions(reply):
    return [b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row]


@pytest.mark.parametrize('day,start,label', [
    ('2026-09-29', '2026-09-28', '28 сентября — 4 октября'),
    ('2026-12-31', '2026-12-28', '28 декабря 2026 — 3 января 2027'),
    ('2027-01-01', '2026-12-28', '28 декабря 2026 — 3 января 2027'),
    ('2026-10-05', '2026-10-05', '5–11 октября'),
])
def test_week_ranges(day, start, label):
    assert weekly.week_start(date.fromisoformat(day)) == date.fromisoformat(start)
    assert weekly.range_label(date.fromisoformat(start)) == label


def test_user_timezone_can_select_another_week(harness, monkeypatch):
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    with harness.SessionLocal() as db:
        owner = user(db, harness)
        owner.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        db.commit()
        summary = weekly.collect_week(db, owner, now_utc=datetime(2026, 10, 4, 15, tzinfo=UTC))
        assert summary.start == NEXT  # Sunday UTC is already Monday locally.


def test_count_duration_and_current_task_stats(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'БД', '10:00', '11:30', day=MONDAY)
        add_lesson(db, harness, 'Английский', '12:00', '13:00', day=MONDAY+timedelta(days=1))
        task(db, harness, is_completed=True, completed_at=datetime(2026, 9, 28, 14))
        task(db, harness, 'Просроченная', deadline=datetime(2026, 9, 28, 18))
        task(db, harness, 'Высокий', priority='high')
        summary = weekly.collect_week(db, user(db, harness), now_utc=NOW)
        assert (summary.lesson_count, summary.duration, summary.completed, summary.active, summary.overdue) == (2, timedelta(minutes=150), 1, 2, 1)
        message = weekly.render_week(summary)
        assert 'Учебное время: 2 ч 30 мин' in message and 'Просроченная' in message
        assert message.count('Главное') == 1 and 'Высокий' not in message


def test_completed_week_boundaries_unknown_and_restored(harness):
    with harness.SessionLocal() as db:
        for stamp, done in [(datetime(2026, 9, 27, 23, 59), True), (datetime(2026, 9, 28), True),
                            (datetime(2026, 9, 29, 11), True), (datetime(2026, 9, 30), True),
                            (None, True), (datetime(2026, 9, 28, 14), False)]:
            task(db, harness, is_completed=done, completed_at=stamp)
        summary = weekly.collect_week(db, user(db, harness), now_utc=NOW)
        assert summary.completed == 2 and summary.active == 1
        assert weekly.collect_week(db, user(db, harness), now_utc=NOW, start=NEXT).completed == 0


@pytest.mark.parametrize('day,hours', [('2026-03-29', 167), ('2026-10-25', 169)])
def test_dst_week_completion_bounds(harness, day, hours):
    local = datetime.fromisoformat(day+'T23:59:59').replace(tzinfo=ZoneInfo('Europe/Berlin'))
    start = datetime.combine(weekly.week_start(local), time.min, tzinfo=local.tzinfo)
    end = start + timedelta(days=7)
    assert (end.astimezone(UTC)-start.astimezone(UTC)).total_seconds() == hours*3600
    with harness.SessionLocal() as db:
        owner = user(db, harness)
        owner.telegram_morning_digest_timezone = 'Europe/Berlin'
        db.commit()
        for instant in [start.astimezone(UTC)-timedelta(seconds=1), start.astimezone(UTC), local.astimezone(UTC), end.astimezone(UTC)]:
            task(db, harness, is_completed=True, completed_at=instant.astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None))
        with patch.object(weekly, 'APP_ZONE', ZoneInfo('Europe/Moscow')):
            assert weekly.collect_week(db, owner, now_utc=local.astimezone(UTC)).completed == 2


@pytest.mark.parametrize('day,minutes', [('2026-03-29', 60), ('2026-10-25', 180)])
def test_dst_lesson_duration_is_elapsed_time(harness, day, minutes):
    day = date.fromisoformat(day)
    with harness.SessionLocal() as db:
        owner = user(db, harness)
        owner.telegram_morning_digest_timezone = 'Europe/Berlin'
        add_lesson(db, harness, day=day, start='01:30', end='03:30')
        summary = weekly.collect_week(db, owner, now_utc=datetime.combine(day, time(12), tzinfo=UTC))
        assert summary.duration == timedelta(minutes=minutes)


def test_incomplete_and_nonexistent_time_are_not_invented(harness):
    with harness.SessionLocal() as db:
        owner = user(db, harness)
        owner.telegram_morning_digest_timezone = 'Europe/Berlin'
        add_lesson(db, harness, day=date(2026,3,29), start='02:30', end='03:30')
        db.add(AcademicEvent(user_id=owner.id, title='Без времени', event_type='changed_class', event_date=date(2026,3,28)))
        db.commit()
        summary = weekly.collect_week(db, owner, now_utc=datetime(2026,3,29,12,tzinfo=UTC))
        assert summary.lesson_count == 2 and summary.duration == timedelta() and summary.unknown_durations == 2
        assert '0 мин' not in weekly.render_week(summary)
        assert 'время указано не полностью' in weekly.render_week(summary)


def test_override_excludes_cancelled_and_counts_moved_by_actual_day(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Отменённая', day=DAY)
        db.add_all([
            AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY),
            AcademicEvent(user_id=harness.first_user_id, title='Перенесённая', event_type='changed_class', event_date=DAY+timedelta(days=1), start_time=time(14), end_time=time(15,30)),
        ])
        db.commit()
        summary = weekly.collect_week(db, user(db, harness), now_utc=NOW)
        assert summary.lesson_count == 1 and summary.duration == timedelta(minutes=90)
        schedule = '\n'.join(weekly.schedule_pages(summary))
        assert 'Отменённая' not in schedule and '14:00 Перенесённая' in schedule


def test_next_week_deadlines_and_no_current_statistics(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Сегодняшняя просрочка', deadline=datetime(2026,9,28,18))
        task(db, harness, 'Первая', deadline=datetime(2026,10,5,0))
        task(db, harness, 'Последняя', deadline=datetime(2026,10,11,23,59))
        task(db, harness, deadline=datetime(2026,10,12,0))
        task(db, harness, deadline=datetime(2026,10,5,18), is_completed=True)
        task(db, harness, scheduled_for_date=NEXT)
        summary = weekly.collect_week(db, user(db,harness), now_utc=NOW, start=NEXT)
        assert summary.deadlines == 2 and summary.important.title == 'Первая'
        message = weekly.render_week(summary)
        assert 'Дедлайнов: 2' in message
        for label in ['Выполнено', 'Активных', 'Просрочено', 'Сегодняшняя просрочка']:
            assert label not in message


@pytest.mark.parametrize('group', ['overdue', 'today', 'week', 'high', 'future', 'none'])
def test_main_task_priority(harness, group):
    options = [('overdue', {'deadline': datetime(2026,9,28,18)}), ('today', {'deadline': datetime(2026,9,29,18)}),
               ('week', {'deadline': datetime(2026,10,2,18)}), ('high', {'priority':'high'}), ('future', {'deadline':datetime(2026,10,8,18)})]
    with harness.SessionLocal() as db:
        chosen = None
        for name, fields in options:
            if name == group or chosen is not None:
                item = task(db,harness,name,**fields)
                chosen = chosen or item
        task(db,harness,'Без срочности')
        summary = weekly.collect_week(db,user(db,harness),now_utc=NOW)
        assert summary.important == chosen


def test_empty_states_no_zero_counters(harness):
    current = callback(harness,'week')
    assert 'На этой неделе занятий нет' in current.text and 'Активных задач нет' in current.text
    upcoming = callback(harness,'week_next')
    assert 'Следующая неделя пока свободна' in upcoming.text
    assert 'Занятий: 0' not in current.text and '0 мин' not in current.text and 'Дедлайнов: 0' not in upcoming.text


def test_navigation_schedule_back_and_legacy_details(harness):
    with harness.SessionLocal() as db:
        add_lesson(db,harness,'Физика',day=NEXT)
    this = callback(harness,'week')
    assert 'Эта неделя' in this.text and 'week_next' in actions(this)
    next_reply = callback(harness,'week_next')
    action = next(x for x in actions(next_reply) if x.startswith('week_schedule:'))
    schedule = callback(harness,action)
    assert '5–11 октября' in schedule.text and '09:00 Физика' in schedule.text
    back = callback(harness,next(x for x in actions(schedule) if x.startswith('week_view:')))
    assert back.text == next_reply.text
    assert 'week_details' in actions(this)
    assert 'Ближайшая неделя' in callback(harness,'week_details').text
    assert len(BOT_COMMANDS) == 6


def test_long_schedule_paginates_without_losing_rows_or_exceeding_utf16_limit(harness):
    with harness.SessionLocal() as db:
        for i in range(85):
            add_lesson(db,harness,f'{i:03d} '+ '🚀<&>'*24, room='🚀'*50, day=MONDAY)
    reply = callback(harness,f'week_schedule:{MONDAY}:0')
    messages = []
    while True:
        assert len(reply.text.encode('utf-16-le'))//2 < 4096
        assert all(len(value.encode())<=64 for value in actions(reply))
        messages.append(reply.text)
        more = [b['callback_data'] for row in reply.reply_markup['inline_keyboard'] for b in row if b['text']=='Следующая страница →']
        if not more:
            break
        reply = callback(harness,more[0])
        assert len(messages)<100
    assert len(messages)>1
    total='\n'.join(messages)
    for i in range(85):
        assert total.count(f'{i:03d} ')==1
    assert '&lt;&amp;&gt;' in total and '🌿 Нет занятий' in total


@pytest.mark.parametrize('value', ['week_schedule:bad:0','week_schedule:2026-09-29:0','week_schedule:2026-09-28:-1','week_schedule:2026-09-28:99999','week_view:9999-12-27'])
def test_invalid_or_stale_callback_is_safe(harness,value):
    assert '⚠️' in callback(harness,value).text


def test_settings_defaults_options_independent_and_preview(harness):
    with harness.SessionLocal() as db:
        assert weekly.preferences(db,user(db,harness)) == {'enabled':False,'day':6,'hour':19}
    assert 'Статус: ❌' in callback(harness,'weekly_settings').text
    callback(harness,'weekly_enable')
    for day in weekly.DAYS:
        assert '✅ '+weekly.DAY_SHORT[day].title() in str(callback(harness,f'weekly_day:{day}').reply_markup)
    for hour in weekly.HOURS:
        assert f'✅ {hour}:00' in str(callback(harness,f'weekly_hour:{hour}').reply_markup)
    with harness.SessionLocal() as db:
        assert weekly.preferences(db,user(db,harness))=={'enabled':True,'day':6,'hour':21}
        assert weekly.preferences(db,db.get(User,harness.second_user_id))=={'enabled':False,'day':6,'hour':19}
    callback(harness,'weekly_day:0')
    callback(harness,'weekly_hour:99')
    assert 'Время: 21:00' in callback(harness,'weekly_settings').text
    assert 'Статус: ❌' in callback(harness,'weekly_disable').text


@pytest.mark.parametrize('day',[4,5,6])
@pytest.mark.parametrize('hour',[18,19,20,21])
def test_scheduler_selected_day_hour_and_dedup(harness,day,hour):
    enable(harness,day=day,hour=hour)
    due=datetime.combine(MONDAY+timedelta(days=day),time(hour-3),tzinfo=UTC)
    assert tick(harness,due-timedelta(seconds=1))==0
    sent=[]
    assert tick(harness,due,sent.append)==1
    assert 'Следующая неделя' in sent[0].text
    assert tick(harness,due+timedelta(minutes=1),sent.append)==0
    assert len(sent)==1


@pytest.mark.parametrize('delay,expected',[(2,1),(15,1),(16,0)])
def test_late_scheduler_window(harness,delay,expected):
    enable(harness)
    assert tick(harness,DUE+timedelta(minutes=delay))==expected


def test_disabled_wrong_day_and_unlink(harness):
    assert tick(harness)==0
    enable(harness)
    assert tick(harness,DUE-timedelta(days=1))==0
    with harness.SessionLocal() as db:
        clear_telegram_link(user(db,harness));db.commit()
    assert tick(harness)==0


def test_retry_failure_not_marked_sent(harness):
    enable(harness)
    send=Mock(side_effect=[TelegramAPIError(category='rate_limit',retry_after=120),None])
    assert tick(harness,send=send)==0
    with harness.SessionLocal() as db:
        row=db.get(TelegramState,f'weekly-digest:{harness.first_user_id}:{NEXT}')
        assert row.data['attempts']==1 and not row.data.get('sent')
    assert tick(harness,DUE+timedelta(minutes=1),send)==0
    assert tick(harness,DUE+timedelta(minutes=2),send)==1
    assert tick(harness,DUE+timedelta(minutes=3),send)==0
    assert send.call_count==2


def test_two_workers_and_restart_keep_week_marker(harness):
    enable(harness)
    sent=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: tick(harness,send=sent.append),range(2)))==1
    assert len(sent)==1
    script='''
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import User
from app.services.telegram_weekly_digest import preferences
from telegram_bot.scheduler import process_weekly_digests
engine=create_engine(sys.argv[1])
with Session(engine) as db:
    assert preferences(db,db.get(User,int(sys.argv[2])))=={'enabled':True,'day':6,'hour':19}
    assert process_weekly_digests(db,now_utc=datetime(2026,10,4,16,2,tzinfo=UTC),send_message=lambda _:None)==0
    assert process_weekly_digests(db,now_utc=datetime(2026,10,11,16,tzinfo=UTC),send_message=lambda _:None)==1
engine.dispose()
'''
    result=subprocess.run([sys.executable,'-c',script,str(harness.engine.url),str(harness.first_user_id)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_changing_send_day_keeps_same_target_week_key(harness):
    enable(harness,day=4)
    assert tick(harness,DUE-timedelta(days=2))==1
    callback(harness,'weekly_day:6')
    assert tick(harness)==0


def test_preview_real_data_no_marker_and_pinned_schedule_after_monday(harness):
    with harness.SessionLocal() as db:
        add_lesson(db,harness,'Реальная пара',day=NEXT)
        task(db,harness,'Реальный дедлайн',deadline=datetime(2026,10,6,18))
    reply=callback(harness,'weekly_preview')
    assert 'Реальная пара' in reply.text and 'Реальный дедлайн' in reply.text
    with harness.SessionLocal() as db:
        assert db.query(TelegramState).filter(TelegramState.key.startswith('weekly-digest:')).count()==0
    enable(harness)
    sent=[]
    assert tick(harness,send=sent.append)==1
    schedule=next(x for x in actions(sent[0]) if x.startswith('week_schedule:'))
    monday=callback(harness,schedule,now=datetime(2026,10,5,9,tzinfo=UTC))
    assert '5–11 октября' in monday.text


def test_two_timezones_scheduler_and_private_ownership(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        other=db.get(User,harness.second_user_id)
        other.telegram_user_id,other.telegram_chat_id=7002,8002
        other.telegram_morning_digest_timezone='Asia/Vladivostok'
        weekly.set_preferences(db,other,enabled=True)
        db.add(Task(user_id=other.id,title='Чужая задача',priority='high'))
        db.commit()
    sent=[]
    assert tick(harness,DUE-timedelta(hours=7),sent.append)==1 and sent[0].chat_id==8002
    assert tick(harness,DUE,sent.append)==1 and sent[1].chat_id==8001
    assert 'Чужая задача' not in callback(harness,'week').text
    with harness.SessionLocal() as db:
        update=harness._callback('week',chat_id=-100)
        update['callback_query']['message']['chat']['type']='supergroup'
        assert 'личный чат' in handle_telegram_update(db,update).text
        assert user(db,harness).telegram_chat_id==8001
        clear_telegram_link(user(db,harness));db.commit()
    for action in ['week','week_next',f'week_schedule:{MONDAY}:0','weekly_preview','weekly_enable']:
        assert 'подключ' in callback(harness,action).text.lower()


def test_scheduler_tick_calls_weekly(harness):
    with harness.SessionLocal() as db, patch.object(scheduler,'retry_pending_replies'), patch.object(scheduler,'process_due_digests'), patch.object(scheduler,'process_deadline_reminders'), patch.object(scheduler,'process_class_reminders'), patch.object(scheduler,'process_evening_digests'), patch.object(scheduler,'process_weekly_digests') as process:
        scheduler.scheduler_tick(db)
        process.assert_called_once_with(db)


def test_week_crossing_year_completion_and_future_deadlines(harness):
    instant=datetime(2026,12,31,18,tzinfo=UTC)
    with harness.SessionLocal() as db:
        task(db,harness,is_completed=True,completed_at=datetime(2026,12,27,23,59))
        task(db,harness,is_completed=True,completed_at=datetime(2026,12,28))
        task(db,harness,deadline=datetime(2027,1,4,18))
        current=weekly.collect_week(db,user(db,harness),now_utc=instant)
        upcoming=weekly.collect_week(db,user(db,harness),now_utc=instant,start=date(2027,1,4))
        assert current.start==date(2026,12,28) and current.completed==1
        assert upcoming.deadlines==1 and upcoming.completed==0


def test_moved_occurrence_is_counted_in_actual_week(harness):
    with harness.SessionLocal() as db:
        moved=AcademicEvent(user_id=harness.first_user_id,title='Перенос на следующую неделю',event_type='changed_class',event_date=NEXT,start_time=time(10),end_time=time(12))
        db.add(moved);db.commit()
        assert weekly.collect_week(db,user(db,harness),now_utc=NOW).lesson_count==0
        future=weekly.collect_week(db,user(db,harness),now_utc=NOW,start=NEXT)
        assert future.lesson_count==1 and future.duration==timedelta(hours=2)


def test_failure_for_one_user_does_not_stop_another(harness):
    enable(harness)
    with harness.SessionLocal() as db:
        other=db.get(User,harness.second_user_id)
        other.telegram_user_id,other.telegram_chat_id=7002,8002
        other.telegram_morning_digest_timezone='Europe/Moscow'
        weekly.set_preferences(db,other,enabled=True)
        db.commit()
    def send(reply):
        if reply.chat_id==8001:
            raise TelegramAPIError(category='blocked')
    assert tick(harness,send=send)==1
    assert tick(harness,DUE+timedelta(minutes=1),send)==0


def test_pending_retry_stops_on_unlink(harness):
    enable(harness)
    assert tick(harness,send=Mock(side_effect=TelegramAPIError(category='network')))==0
    with harness.SessionLocal() as db:
        clear_telegram_link(user(db,harness));db.commit()
    assert tick(harness,DUE+timedelta(minutes=1))==0


def test_automatic_digest_omits_past_stats_and_has_existing_callbacks(harness):
    with harness.SessionLocal() as db:
        add_lesson(db,harness,'Базы данных',start='10:40',end='12:10',day=NEXT)
        task(db,harness,deadline=datetime(2026,10,6,18))
        task(db,harness,is_completed=True,completed_at=datetime(2026,9,29,11))
        message=weekly.automatic_message(db,user(db,harness),now_utc=DUE)
        markup=weekly.automatic_keyboard(user(db,harness),DUE)
    assert 'Понедельник · 10:40 · Базы данных' in message
    assert 'Выполнено' not in message and 'Активных' not in message
    data=[b['callback_data'] for row in markup['inline_keyboard'] for b in row]
    assert data==[f'week_schedule:{NEXT}:0','tasks','weekly_settings']
