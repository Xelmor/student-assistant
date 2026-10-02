"""Menu changes leave existing business actions and privacy checks intact."""
from dataclasses import replace
from unittest.mock import patch

import pytest

import test_telegram_bot as harness_module
from app.core.config import settings
from app.models import Task, TelegramState, User
from app.services.telegram_bot import BOT_COMMANDS, build_help_message, generate_link_code, handle_telegram_update
from telegram_bot import set_commands


@pytest.fixture
def harness():
    case = harness_module.TelegramBotTests()
    case._testMethodName = 'navigation'
    case.setUp()
    yield case
    case.tearDown()


def link_user(db, harness):
    user = db.get(User, harness.first_user_id)
    user.telegram_user_id, user.telegram_chat_id = 7001, 8001
    db.commit()
    return user


def rows(reply):
    return reply.reply_markup['inline_keyboard']


def buttons(reply):
    return [button for row in rows(reply) for button in row]


def callback(db, harness, button):
    reply = handle_telegram_update(db, harness._callback(button['callback_data']))
    assert reply.callback_query_id == f"callback-{button['callback_data']}"
    return reply


def test_setup_publishes_exactly_six_commands(capsys):
    with patch('telegram_bot.set_commands.settings', replace(settings, telegram_bot_token='isolated-token')), patch('app.services.telegram_bot.call_telegram_api') as api:
        assert set_commands.main() == 0
    published = api.call_args.args
    assert published == ('setMyCommands', {'commands': BOT_COMMANDS})
    assert len(published[1]['commands']) == 6
    assert [item['command'] for item in BOT_COMMANDS] == ['start', 'today', 'tomorrow', 'week', 'tasks', 'add_task']
    assert '6 commands' in capsys.readouterr().out


def test_linked_main_menu_and_settings_back(harness):
    with harness.SessionLocal() as db:
        user = link_user(db, harness)
        menu = handle_telegram_update(db, harness._update('/start'))
        assert [[button['text'] for button in row] for row in rows(menu)] == [
            ['📍 Сейчас'],
            ['📅 Сегодня', '📆 Завтра'], ['🗓 Неделя', '📌 Задачи'],
            ['➕ Добавить задачу'], ['📝 Заметка'], ['⚙️ Настройки', '🌐 Сайт'],
        ]
        preferences = callback(db, harness, rows(menu)[5][0])
        assert [[button['text'] for button in row] for row in rows(preferences)] == [
            ['🌅 Утренняя сводка'], ['⏰ Напоминания о дедлайнах'],
            ['🔗 Статус подключения'], ['🚪 Отключить Telegram'], ['🎓 Пары'], ['🌙 Вечерняя сводка'], ['← Назад'],
        ]
        back = callback(db, harness, buttons(preferences)[-1])
        assert back.reply_markup == menu.reply_markup
        assert user.telegram_user_id == 7001
        assert not user.telegram_morning_digest_enabled
        assert not user.telegram_deadline_reminders_enabled


def test_unlinked_menu_only_offers_connection_and_site(harness):
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._update('/start'))
        assert [button['text'] for button in buttons(reply)] == ['🔗 Подключить Telegram', '🌐 Открыть сайт']
        assert len(reply.text) < 200
        assert '/link' not in reply.text
        assert '📅' not in reply.text
        instruction = callback(db, harness, buttons(reply)[0])
        assert '<code>/link CODE</code>' in instruction.text
        assert 'профиль' in instruction.text
        assert db.get(User, harness.first_user_id).telegram_user_id is None
        back = callback(db, harness, buttons(instruction)[-1])
        assert back.reply_markup == reply.reply_markup


def test_settings_reuse_existing_digest_deadline_status_unlink_actions(harness):
    with harness.SessionLocal() as db:
        user = link_user(db, harness)
        menu = handle_telegram_update(db, harness._callback('settings'))
        digest = callback(db, harness, buttons(menu)[0])
        assert 'Утренняя сводка' in digest.text
        enabled = callback(db, harness, buttons(digest)[0])
        assert user.telegram_morning_digest_enabled
        back = callback(db, harness, buttons(enabled)[-1])
        assert back.reply_markup == menu.reply_markup

        deadlines = callback(db, harness, buttons(menu)[1])
        assert 'Напоминания о дедлайнах' in deadlines.text
        enabled = callback(db, harness, buttons(deadlines)[0])
        assert user.telegram_deadline_reminders_enabled
        hours = next(button for button in buttons(enabled) if button.get('callback_data') == 'deadline_hours:6')
        changed = callback(db, harness, hours)
        assert user.telegram_deadline_reminder_hours == 6
        assert callback(db, harness, buttons(changed)[-1]).reply_markup == menu.reply_markup

        status = callback(db, harness, buttons(menu)[2])
        assert 'Telegram подключён' in status.text
        assert 'Лёля' in status.text
        assert callback(db, harness, buttons(status)[-1]).reply_markup == menu.reply_markup
        unlink = callback(db, harness, buttons(menu)[3])
        assert 'Отключить Telegram?' in unlink.text
        assert buttons(unlink)[0]['callback_data'] == 'unlink_confirm'
        assert user.telegram_user_id == 7001  # Still requires the existing confirmation.
        assert db.get(User, harness.second_user_id).telegram_user_id is None


HIDDEN_EXPECTATIONS = [
    ('help', 'Что умеет Student Assistant:'), ('link', 'Telegram подключён!'),
    ('notifications', 'Telegram-уведомления'), ('digest', 'Утренняя сводка'),
    ('digest_on', 'включена'), ('digest_off', 'выключена'),
    ('digest_test', 'Доброе утро'), ('done', 'Задача выполнена'),
    ('cancel', 'Действие отменено'), ('site', 'Student Assistant'),
    ('unlink', 'Отключить Telegram?'),
]


@pytest.mark.parametrize('command,expected', HIDDEN_EXPECTATIONS)
def test_hidden_commands_still_work(harness, command, expected):
    assert command not in {item['command'] for item in BOT_COMMANDS}
    with harness.SessionLocal() as db:
        argument = ''
        if command == 'link':
            user = db.get(User, harness.first_user_id)
            argument = ' ' + generate_link_code(db, user)
        else:
            user = link_user(db, harness)
        if command == 'done':
            db.add(Task(user_id=user.id, title='Закрываемая задача'))
            db.commit()
            handle_telegram_update(db, harness._update('/tasks'))
            argument = ' 1'
        elif command == 'cancel':
            handle_telegram_update(db, harness._update('/add_task'))
        elif command == 'digest_off':
            user.telegram_morning_digest_enabled = True
            db.commit()
        reply = handle_telegram_update(db, harness._update('/' + command + argument))
        assert expected in reply.text
        if command == 'done':
            assert db.query(Task).one().is_completed
        elif command == 'cancel':
            assert db.get(TelegramState, 'dialog:7001').data == {}
        elif command == 'link':
            assert user.telegram_user_id == 7001
        elif command in {'digest_on', 'digest_off'}:
            assert user.telegram_morning_digest_enabled is (command == 'digest_on')


def test_help_has_only_short_student_feature_list():
    assert build_help_message().splitlines() == [
        '<b>Что умеет Student Assistant:</b>', '📅 Сегодня', '📆 Завтра',
        '🗓 Неделя', '📌 Задачи', '➕ Добавить задачу', '⚙️ Настройки',
    ]


def test_cancel_button_stays_available_during_navigation_and_cancel_always_works(harness):
    with harness.SessionLocal() as db:
        link_user(db, harness)
        reply = handle_telegram_update(db, harness._update('/add_task'))
        assert buttons(reply)[0]['text'] == '❌ Отменить'
        settings_menu = handle_telegram_update(db, harness._callback('settings'))
        cancel = next(button for button in buttons(settings_menu) if button['text'] == '❌ Отменить')
        reply = callback(db, harness, cancel)
        assert 'отменено' in reply.text
        assert db.get(TelegramState, 'dialog:7001').data == {}
        reply = handle_telegram_update(db, harness._update('/cancel'))
        assert 'нет активного действия' in reply.text
    with harness.SessionLocal() as db:
        reply = handle_telegram_update(db, harness._update('/cancel', telegram_user_id=9999))
        assert 'нет активного действия' in reply.text


@pytest.mark.parametrize('action', ['settings', 'connection_status', 'deadline_settings', 'connect'])
def test_new_navigation_is_private_and_does_not_expose_unlinked_users(harness, action):
    with harness.SessionLocal() as db:
        user = link_user(db, harness)
        update = harness._callback(action, chat_id=-100)
        update['callback_query']['message']['chat']['type'] = 'group'
        reply = handle_telegram_update(db, update)
        assert reply.text == 'Открой личный чат с ботом.'
        assert user.telegram_chat_id == 8001
        outsider = handle_telegram_update(db, harness._callback(action, telegram_user_id=9999, chat_id=9999))
        assert 'Лёля' not in outsider.text
        assert '7001' not in outsider.text
        assert not user.telegram_morning_digest_enabled
        assert not user.telegram_deadline_reminders_enabled
