from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch

import pytest

from app.models import AcademicEvent, Task, User
from app.services.telegram_bot import BOT_COMMANDS, handle_telegram_update
from app.services.telegram_now import build_now_message
from app.services.telegram_today import build_today_schedule, build_today_summary, plural
from test_telegram_now import DAY, MOSCOW, add_lesson, harness, two_lessons


def instant(clock='09:20'):
    return datetime.fromisoformat(f'{DAY}T{clock}').replace(tzinfo=MOSCOW).astimezone(UTC)


def summary(db, harness, clock='09:20'):
    return build_today_summary(db, db.get(User, harness.first_user_id), now_utc=instant(clock))


def schedule(db, harness):
    return build_today_schedule(db, db.get(User, harness.first_user_id), now_utc=instant())


def task(db, harness, title='Практика', deadline='2026-09-29T18:00', **kwargs):
    value = Task(user_id=kwargs.pop('user_id', harness.first_user_id), title=title,
                 deadline=datetime.fromisoformat(deadline) if deadline else None,
                 created_at=datetime(2026, 9, 28, 12), **kwargs)
    db.add(value)
    db.commit()
    return value


def callback(db, harness, action='today', clock='09:20', **kwargs):
    with patch('app.services.telegram_bot.digest_local_datetime', return_value=instant(clock)):
        return handle_telegram_update(db, harness._callback(action, **kwargs))


def test_normal_day_is_a_short_summary_not_a_full_schedule(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        add_lesson(db, harness, 'Третья пара', '14:00', '15:30')
        task(db, harness, 'Практика по БД')
        task(db, harness, 'Выучить слова', deadline=None, priority='high')
        task(db, harness, 'Купить тетрадь', deadline=None)
        text = summary(db, harness)
        assert text == (
            '📅 <b>Сегодня</b>, 29 сентября\n\n'
            '🎓 3 занятия\n📌 3 активные задачи\n⏰ 1 дедлайн сегодня\n\n━━━━━━━━━━━━━━\n\n'
            '📍 <b>Сейчас</b>\nМатематика · 09:00–10:30\nАуд. 301 · до конца: 1 ч 10 мин\n\n'
            'Дальше:\nФизика · 11:30–13:00\nАуд. 205 · через 2 ч 10 мин\n\n━━━━━━━━━━━━━━\n\n'
            '🔴 <b>Главное на сегодня</b>\n🟡 Практика по БД · до 18:00\n🔴 Выучить слова · высокий приоритет'
        )
        assert 'Третья пара' not in text and 'Купить тетрадь' not in text


@pytest.mark.parametrize('clock,status,detail', [
    ('08:13', 'Учебный день ещё не начался', 'через 47 мин'),
    ('09:00', 'Математика · 09:00–10:30', 'до конца: 1 ч 30 мин'),
    ('09:20', 'Математика · 09:00–10:30', 'до конца: 1 ч 10 мин'),
    ('10:30', 'Свободное окно', 'через 1 ч'),
    ('10:43', 'Свободное окно', 'через 47 мин'),
    ('11:30', 'Физика · 11:30–13:00', 'Это последняя пара на сегодня.'),
    ('13:00', 'Занятия на сегодня закончились', 'На сегодня срочных задач нет ✅'),
])
def test_schedule_statuses_and_boundaries(harness, clock, status, detail):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        text = summary(db, harness, clock)
        assert status in text and detail in text
        assert '📌 0 активных задач' in text


def test_empty_day_is_calm(harness):
    with harness.SessionLocal() as db:
        text = summary(db, harness)
        assert '🌿 Сегодня спокойно\n\nЗанятий нет.\nСрочных задач тоже нет.' in text
        assert '🎓 0 занятий' in text and '⏰ 0 дедлайнов сегодня' in text


def test_tasks_without_lessons_and_overdue_marker(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Долг', '2026-09-28T18:00')
        text = summary(db, harness)
        assert '🌿 Сегодня без занятий' in text
        assert '🔴 Долг · до 28.09 18:00 · просрочено' in text
        assert 'Сегодня спокойно' not in text


def test_today_deadline_and_high_priority(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Дедлайн сегодня')
        task(db, harness, 'Важно без даты', None, priority='high')
        text = summary(db, harness)
        assert '⏰ 1 дедлайн сегодня' in text
        assert '🟡 Дедлайн сегодня · до 18:00' in text
        assert '🔴 Важно без даты · высокий приоритет' in text


def test_completed_and_other_users_tasks_are_excluded(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Готово', is_completed=True)
        task(db, harness, 'Чужой секрет', user_id=harness.second_user_id)
        text = summary(db, harness)
        assert 'Готово' not in text and 'Чужой секрет' not in text
        assert '📌 0 активных задач' in text and '⏰ 0 дедлайнов сегодня' in text


def test_at_most_three_ranked_overdue_today_high_then_nearest(harness):
    with harness.SessionLocal() as db:
        future = task(db, harness, 'Скоро', '2026-09-30T08:00')
        high = task(db, harness, 'Приоритет', None, priority='high')
        today = task(db, harness, 'Сегодняшняя', '2026-09-29T18:00')
        overdue = task(db, harness, 'Просрочка', '2026-09-28T18:00')
        task(db, harness, 'Потом', '2026-10-05T18:00')
        text = summary(db, harness)
        assert text.index('Просрочка') < text.index('Сегодняшняя') < text.index('Приоритет')
        assert 'Скоро' not in text and 'Потом' not in text
        assert '📌 5 активных задач' in text
        overdue.is_completed = True
        db.commit()
        text = summary(db, harness)
        assert text.index('Сегодняшняя') < text.index('Приоритет') < text.index('Скоро')
        assert 'Потом' not in text


def test_nearest_deadlines_are_sorted_and_not_called_urgent(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Позже', '2026-10-03T10:00')
        task(db, harness, 'Ближе', '2026-09-30T10:00')
        text = summary(db, harness)
        assert 'На сегодня срочных задач нет ✅' in text
        assert 'Ближайшие задачи' in text
        assert text.index('Ближе') < text.index('Позже')
        assert 'высокий приоритет' not in text


def test_unscheduled_normal_task_is_counted_but_not_urgent(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Когда-нибудь', None)
        text = summary(db, harness)
        assert '📌 1 активная задача' in text
        assert 'На сегодня срочных задач нет ✅' in text
        assert 'Когда-нибудь' not in text


def test_scheduled_day_task_uses_existing_anchor(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'К занятию', None, scheduled_for_date=DAY)
        text = summary(db, harness)
        assert 'К занятию · сегодня' in text
        assert '⏰ 1 дедлайн сегодня' in text


def test_deadline_becomes_overdue_after_its_exact_time(harness):
    with harness.SessionLocal() as db:
        task(db, harness, 'Сдать', '2026-09-29T09:20')
        assert 'просрочено' not in summary(db, harness)
        assert 'просрочено' in summary(db, harness, '09:20:01')


def test_override_and_replacement_match_now_and_expanded_schedule(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Старая пара')
        db.add_all([
            AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY),
            AcademicEvent(user_id=harness.first_user_id, title='Новая пара', event_type='changed_class',
                          event_date=DAY, start_time=time(9), end_time=time(10, 30), room='205'),
        ])
        db.commit()
        text = summary(db, harness)
        assert '🎓 1 занятие' in text and 'Новая пара' in text and 'Старая пара' not in text
        now = build_now_message(db, db.get(User, harness.first_user_id), now_utc=instant())
        assert 'Новая пара' in now and 'Старая пара' not in now
        expanded = schedule(db, harness)
        assert 'Старая пара\n❌ Отменено' in expanded
        assert 'Новая пара\nАуд. 205\n🔄 Изменение расписания' in expanded
        assert '→' not in expanded  # No original-time relationship exists in the database.


def test_other_users_override_and_lessons_do_not_leak(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        add_lesson(db, harness, 'Чужая пара', user_id=harness.second_user_id)
        db.add(AcademicEvent(user_id=harness.second_user_id, title='Чужая отмена', event_type='day_override', event_date=DAY))
        db.commit()
        assert 'Математика' in summary(db, harness)
        assert 'Чуж' not in summary(db, harness) and 'Чуж' not in schedule(db, harness)
        assert 'Отменено' not in schedule(db, harness)


def test_cancelled_day_count_is_zero(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness)
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Отмена', event_type='day_override', event_date=DAY))
        db.commit()
        assert '🎓 0 занятий' in summary(db, harness)
        assert 'Математика\n❌ Отменено' in schedule(db, harness)


def test_user_timezone_controls_day_lessons_and_deadlines(harness):
    with harness.SessionLocal() as db:
        user = db.get(User, harness.first_user_id)
        user.telegram_morning_digest_timezone = 'Asia/Vladivostok'
        add_lesson(db, harness)
        task(db, harness, 'Сегодня у пользователя')
        text = build_today_summary(db, user, now_utc=datetime(2026, 9, 28, 23, 20, tzinfo=UTC))
        assert '29 сентября' in text
        assert 'до конца: 1 ч 10 мин' in text
        assert '⏰ 1 дедлайн сегодня' in text


@pytest.mark.parametrize('room', [None, '', '  '])
def test_no_empty_room_label(harness, room):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, room=room)
        assert 'Ауд.' not in summary(db, harness)
        assert 'Ауд.' not in schedule(db, harness)


def test_html_is_escaped_in_tasks_and_schedule(harness):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, '<Математика&>', room='<301>')
        task(db, harness, '<Задача&>')
        text = summary(db, harness)
        assert '&lt;Задача&amp;&gt;' in text and '&lt;Математика&amp;&gt;' in text
        assert '&lt;301&gt;' in schedule(db, harness)


def test_incomplete_lesson_time_is_not_fabricated(harness):
    with harness.SessionLocal() as db:
        db.add(AcademicEvent(user_id=harness.first_user_id, title='Уточнить', event_type='changed_class', event_date=DAY))
        db.commit()
        assert 'Время занятий указано не полностью' in summary(db, harness)
        assert 'Время не указано' in schedule(db, harness)
        assert '00:00' not in schedule(db, harness)


def test_callbacks_keyboard_refresh_and_full_schedule(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        reply = callback(db, harness)
        assert reply.callback_query_id == 'callback-today'
        assert reply.reply_markup == {'inline_keyboard': [
            [{'text': '📍 Сейчас', 'callback_data': 'now'}, {'text': '🗓 Расписание', 'callback_data': 'today_schedule'}],
            [{'text': '📌 Все задачи', 'callback_data': 'tasks'}, {'text': '➕ Добавить задачу', 'callback_data': 'add_task_start'}],
            [{'text': '🔄 Обновить', 'callback_data': 'today'}],
        ]}
        expanded = callback(db, harness, 'today_schedule')
        assert expanded.callback_query_id == 'callback-today_schedule'
        assert expanded.text == ('🗓 <b>Расписание на сегодня</b>\n\n09:00–10:30\nМатематика\nАуд. 301'
                                 '\n\n11:30–13:00\nФизика\nАуд. 205')
        assert expanded.reply_markup == {'inline_keyboard': [
            [{'text': '← Сегодня', 'callback_data': 'today'}],
            [{'text': '📍 Сейчас', 'callback_data': 'now'}],
        ]}
        refresh = reply.reply_markup['inline_keyboard'][2][0]['callback_data']
        assert 'Свободное окно' in callback(db, harness, refresh, clock='10:43').text
        assert 'через 47 мин' in callback(db, harness, refresh, clock='10:43').text


def test_command_and_callback_give_same_summary(harness):
    with harness.SessionLocal() as db:
        two_lessons(db, harness)
        with patch('app.services.telegram_bot.digest_local_datetime', return_value=instant()):
            command = handle_telegram_update(db, harness._update('/today'))
        assert command.text == callback(db, harness).text


def test_website_completion_is_visible_on_next_today(harness):
    with harness.SessionLocal() as db:
        value = task(db, harness, 'Закрыть на сайте')
        task_id = value.id
        assert value.title in callback(db, harness).text
    harness._login()
    csrf = harness._csrf(harness.client.get('/tasks').text)
    response = harness.client.post(f'/tasks/toggle/{task_id}', data={'csrf_token': csrf}, follow_redirects=False)
    assert response.status_code == 302
    with harness.SessionLocal() as db:
        text = callback(db, harness).text
        assert 'Закрыть на сайте' not in text
        assert '📌 0 активных задач' in text


@pytest.mark.parametrize('action', ['today', 'today_schedule'])
def test_unlinked_user_cannot_read_day(harness, action):
    with harness.SessionLocal() as db:
        add_lesson(db, harness, 'Секрет')
        task(db, harness, 'Секретная задача')
        reply = callback(db, harness, action, telegram_user_id=9999)
        assert 'Аккаунт не подключён' in reply.text and 'Секрет' not in reply.text


@pytest.mark.parametrize('action', ['today', 'today_schedule'])
@pytest.mark.parametrize('kind', ['callback', 'command'])
def test_group_cannot_read_day_or_rebind_chat(harness, action, kind):
    update = harness._callback(action, chat_id=-55) if kind == 'callback' else harness._update('/' + action, chat_id=-55)
    message = update['callback_query']['message'] if kind == 'callback' else update['message']
    message['chat']['type'] = 'supergroup'
    with harness.SessionLocal() as db:
        with patch('app.services.telegram_bot.build_today_summary') as summary_builder, patch('app.services.telegram_bot.build_today_schedule') as schedule_builder:
            reply = handle_telegram_update(db, update)
        summary_builder.assert_not_called()
        schedule_builder.assert_not_called()
        assert reply.text == 'Открой личный чат с ботом.'
        assert db.get(User, harness.first_user_id).telegram_chat_id == 8001


@pytest.mark.parametrize('count,index', [(0, 2), (1, 0), (2, 1), (5, 2), (11, 2), (12, 2), (14, 2), (21, 0), (22, 1), (25, 2), (111, 2)])
def test_russian_counter_forms(count, index):
    for forms in [('занятие', 'занятия', 'занятий'), ('активная задача', 'активные задачи', 'активных задач'), ('дедлайн сегодня', 'дедлайна сегодня', 'дедлайнов сегодня')]:
        assert plural(count, *forms) == f'{count} {forms[index]}'


def test_public_commands_unchanged():
    assert [item['command'] for item in BOT_COMMANDS] == ['start', 'today', 'tomorrow', 'week', 'tasks', 'add_task']
