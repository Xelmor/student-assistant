from __future__ import annotations

import re
import unittest
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.core.time import current_date, current_time
from app.main import app
from app.models import (
    AcademicEvent,
    ScheduleItem,
    Subject,
    Task,
    TelegramDeadlineReminderLog,
    User,
)
from app.services.telegram_bot import (
    BOT_COMMANDS,
    MESSAGE_DIVIDER,
    TelegramAPIError,
    TelegramReply,
    build_help_message,
    build_digest_settings_message,
    build_link_success_message,
    build_notifications_settings_message,
    build_site_message,
    build_start_linked_message,
    build_start_unlinked_message,
    build_tasks_message,
    build_unlink_confirm_message,
    build_unknown_command_message,
    clear_telegram_dialog_states,
    generate_link_code,
    get_telegram_updates,
    handle_telegram_update,
    install_telegram_commands,
    parse_telegram_deadline,
    send_telegram_message,
)
from app.services.telegram_digest import build_morning_digest_message
from telegram_bot import polling
from telegram_bot import scheduler


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        clear_telegram_dialog_states()
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        self.db_path = temp_dir / f'{self._testMethodName}_telegram.db'
        if self.db_path.exists():
            self.db_path.unlink()

        self.engine = create_engine(
            f"sqlite:///{self.db_path.resolve().as_posix()}",
            connect_args={'check_same_thread': False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            first = User(
                username='telegram-first',
                email='telegram-first@example.com',
                password_hash=hash_password('password123'),
                display_name='Лёля',
            )
            second = User(
                username='telegram-second',
                email='telegram-second@example.com',
                password_hash=hash_password('password123'),
            )
            db.add_all([first, second])
            db.commit()
            self.first_user_id = first.id
            self.second_user_id = second.id

    def tearDown(self):
        clear_telegram_dialog_states()
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    @staticmethod
    def _update(command: str, *, telegram_user_id: int = 7001, chat_id: int = 8001):
        return {
            'message': {
                'text': command,
                'chat': {'id': chat_id, 'type': 'private'},
                'from': {'id': telegram_user_id, 'username': 'student_test'},
            }
        }

    @staticmethod
    def _callback(action: str, *, telegram_user_id: int = 7001, chat_id: int = 8001):
        return {
            'callback_query': {
                'id': f'callback-{action}',
                'data': action,
                'message': {'chat': {'id': chat_id, 'type': 'private'}},
                'from': {'id': telegram_user_id, 'username': 'student_test'},
            }
        }

    @staticmethod
    def _csrf(html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if match is None:
            raise AssertionError('CSRF token was not rendered.')
        return match.group(1)

    def _login(self):
        csrf = self._csrf(self.client.get('/login').text)
        response = self.client.post(
            '/login',
            data={
                'username': 'telegram-first',
                'password': 'password123',
                'csrf_token': csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_profile_creates_single_use_link_code(self):
        self._login()
        csrf = self._csrf(self.client.get('/profile').text)
        response = self.client.post(
            '/profile/telegram/link-code',
            data={'csrf_token': csrf},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('telegram_status=code-created', response.headers['location'])
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            self.assertRegex(user.telegram_link_code or '', r'^[A-Z2-9]{6}$')
            self.assertGreater(user.telegram_link_code_expires_at, current_time())

    def test_link_command_connects_account_and_consumes_code(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            code = generate_link_code(db, user)

            reply = handle_telegram_update(db, self._update(f'/link {code}'))
            db.refresh(user)

            self.assertIn('Telegram подключён!', reply.text)
            self.assertEqual(reply.parse_mode, 'HTML')
            self.assertEqual(
                reply.reply_markup['inline_keyboard'][0][0]['callback_data'],
                'today',
            )
            self.assertEqual(user.telegram_user_id, 7001)
            self.assertEqual(user.telegram_chat_id, 8001)
            self.assertEqual(user.telegram_username, 'student_test')
            self.assertIsNone(user.telegram_link_code)
            self.assertIsNone(user.telegram_link_code_expires_at)

    def test_wrong_and_expired_codes_are_rejected(self):
        with self.SessionLocal() as db:
            wrong_reply = handle_telegram_update(db, self._update('/link BAD999'))
            self.assertIn('не найден или истёк', wrong_reply.text)

            user = db.get(User, self.first_user_id)
            user.telegram_link_code = 'ABC234'
            user.telegram_link_code_expires_at = current_time() - timedelta(minutes=1)
            db.commit()

            expired_reply = handle_telegram_update(db, self._update('/link ABC234'))
            db.refresh(user)
            self.assertIn('не найден или истёк', expired_reply.text)
            self.assertIsNone(user.telegram_link_code)

    def test_tasks_only_include_linked_users_data(self):
        with self.SessionLocal() as db:
            first = db.get(User, self.first_user_id)
            second = db.get(User, self.second_user_id)
            first.telegram_user_id = 7001
            first.telegram_chat_id = 8001
            db.add_all(
                [
                    Task(
                        user_id=first.id,
                        title='Visible Telegram task',
                        deadline=current_time() + timedelta(hours=2),
                        is_completed=False,
                    ),
                    Task(
                        user_id=second.id,
                        title='Other user private task',
                        deadline=current_time() + timedelta(hours=1),
                        is_completed=False,
                    ),
                    Task(
                        user_id=first.id,
                        title='Completed task',
                        deadline=current_time() + timedelta(hours=1),
                        is_completed=True,
                    ),
                ]
            )
            db.commit()

            reply = handle_telegram_update(db, self._update('/tasks'))

            self.assertIn('Visible Telegram task', reply.text)
            self.assertNotIn('Other user private task', reply.text)
            self.assertNotIn('Completed task', reply.text)

    def test_add_task_requires_linked_account(self):
        with self.SessionLocal() as db:
            reply = handle_telegram_update(
                db,
                self._update('/add_task Чужая задача'),
            )

            self.assertIn('Аккаунт не подключён', reply.text)
            self.assertEqual(db.query(Task).count(), 0)
            buttons = reply.reply_markup['inline_keyboard'][0]
            self.assertEqual(buttons[0]['text'], '🌐 Открыть сайт')
            self.assertEqual(buttons[1]['callback_data'], 'help')

    def test_add_task_without_text_starts_dialog(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            command_reply = handle_telegram_update(db, self._update('/add_task'))

            self.assertIn('<b>Новая задача</b>', command_reply.text)
            self.assertIn('Напиши название', command_reply.text)
            self.assertEqual(
                command_reply.reply_markup['inline_keyboard'][0][0]['callback_data'],
                'add_task_cancel',
            )
            self.assertEqual(db.query(Task).count(), 0)

    def test_add_task_with_title_creates_active_task_for_linked_user(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            reply = handle_telegram_update(
                db,
                self._update('/add_task Сделать практику по ТПР'),
            )

            task = db.query(Task).one()
            self.assertIn('Задача добавлена', reply.text)
            self.assertIn('Сделать практику по ТПР', reply.text)
            self.assertEqual(task.user_id, self.first_user_id)
            self.assertIsNone(task.subject_id)
            self.assertIsNone(task.deadline)
            self.assertEqual(task.priority, 'medium')
            self.assertEqual(task.difficulty, 'medium')
            self.assertFalse(task.is_completed)
            callbacks = [
                button.get('callback_data')
                for row in reply.reply_markup['inline_keyboard']
                for button in row
                if button.get('callback_data')
            ]
            self.assertEqual(callbacks, ['tasks', 'add_task_start', 'site'])

    def test_add_task_extended_format_links_owned_subject(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            subject = Subject(user_id=user.id, name='ТПР')
            db.add(subject)
            db.commit()

            reply = handle_telegram_update(
                db,
                self._update(
                    '/add_task Сделать отчёт, завтра 18:00, тпр, высокий'
                ),
            )

            task = db.query(Task).one()
            self.assertEqual(task.user_id, self.first_user_id)
            self.assertEqual(task.subject_id, subject.id)
            self.assertEqual(task.deadline.date(), current_date() + timedelta(days=1))
            self.assertEqual(task.deadline.time(), time(18, 0))
            self.assertEqual(task.priority, 'high')
            self.assertIn('🔴 высокий', reply.text)
            self.assertIn('Предмет: ТПР', reply.text)

    def test_add_task_unknown_values_use_safe_fallbacks(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            other_subject = Subject(user_id=self.second_user_id, name='Секретный предмет')
            db.add(other_subject)
            db.commit()

            reply = handle_telegram_update(
                db,
                self._update(
                    '/add_task Проверить отчёт, когда-нибудь, '
                    'Секретный предмет, срочный'
                ),
            )

            task = db.query(Task).filter(Task.user_id == user.id).one()
            self.assertIsNone(task.subject_id)
            self.assertIsNone(task.deadline)
            self.assertEqual(task.priority, 'medium')
            self.assertIn('Дедлайн не удалось распознать', reply.text)
            self.assertIn('Предмет не найден', reply.text)
            self.assertNotIn('Секретный предмет', reply.text)

    def test_add_task_keeps_legacy_pipe_format_compatible(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            reply = handle_telegram_update(
                db,
                self._update('/add_task Старый формат | сегодня 19:00 | | low'),
            )

            task = db.query(Task).one()
            self.assertIn('Задача добавлена', reply.text)
            self.assertEqual(task.title, 'Старый формат')
            self.assertEqual(task.deadline.time(), time(19, 0))
            self.assertEqual(task.priority, 'low')

    def test_add_task_escapes_title_and_appears_in_tasks(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            created = handle_telegram_update(
                db,
                self._update('/add_task <Отчёт & практика>'),
            )
            listed = handle_telegram_update(db, self._update('/tasks'))

            self.assertIn('&lt;Отчёт &amp; практика&gt;', created.text)
            self.assertIn('&lt;Отчёт &amp; практика&gt;', listed.text)
            self.assertNotIn('<Отчёт & практика>', created.text)

    def test_add_task_dialog_saves_title_today_priority_and_creates_task(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            deadline_step = handle_telegram_update(
                db,
                self._update('Сделать практику по Python'),
            )
            subject_step = handle_telegram_update(
                db,
                self._callback('add_task_deadline_today'),
            )
            priority_step = handle_telegram_update(
                db,
                self._callback('add_task_subject_none'),
            )
            confirmation = handle_telegram_update(
                db,
                self._callback('add_task_priority_high'),
            )
            created = handle_telegram_update(
                db,
                self._callback('add_task_confirm_create'),
            )

            task = db.query(Task).one()
            self.assertIn('<b>Когда дедлайн?</b>', deadline_step.text)
            self.assertIn('<b>К какому предмету', subject_step.text)
            self.assertIn('<b>Выбери приоритет</b>', priority_step.text)
            self.assertIn('Сделать практику по Python', confirmation.text)
            self.assertIn('🔴 высокий', confirmation.text)
            self.assertIn('Задача добавлена', created.text)
            self.assertEqual(task.title, 'Сделать практику по Python')
            self.assertEqual(task.deadline.date(), current_date())
            self.assertEqual(task.deadline.time(), time(23, 59))
            self.assertEqual(task.priority, 'high')
            self.assertIsNone(task.subject_id)

    def test_add_task_dialog_supports_tomorrow_and_no_deadline(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            handle_telegram_update(db, self._update('Задача на завтра'))
            handle_telegram_update(db, self._callback('add_task_deadline_tomorrow'))
            handle_telegram_update(db, self._callback('add_task_subject_none'))
            handle_telegram_update(db, self._callback('add_task_priority_medium'))
            handle_telegram_update(db, self._callback('add_task_confirm_create'))

            tomorrow_task = db.query(Task).one()
            self.assertEqual(
                tomorrow_task.deadline.date(),
                current_date() + timedelta(days=1),
            )

            handle_telegram_update(db, self._update('/add_task'))
            handle_telegram_update(db, self._update('Задача без даты'))
            handle_telegram_update(db, self._callback('add_task_deadline_none'))
            handle_telegram_update(db, self._callback('add_task_subject_none'))
            handle_telegram_update(db, self._callback('add_task_priority_low'))
            handle_telegram_update(db, self._callback('add_task_confirm_create'))

            undated = db.query(Task).filter(Task.title == 'Задача без даты').one()
            self.assertIsNone(undated.deadline)
            self.assertEqual(undated.priority, 'low')

    def test_add_task_dialog_custom_deadline_retries_and_accepts_russian_date(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            handle_telegram_update(db, self._update('Задача с датой'))
            prompt = handle_telegram_update(
                db,
                self._callback('add_task_deadline_custom'),
            )
            invalid = handle_telegram_update(db, self._update('после каникул'))
            subject = handle_telegram_update(db, self._update('15.06.2026'))

            self.assertIn('15.06.2026', prompt.text)
            self.assertIn('Не получилось распознать дату', invalid.text)
            self.assertIn('К какому предмету', subject.text)

    def test_add_task_dialog_subject_selection_is_scoped_to_user(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            owned = Subject(user_id=user.id, name='Python')
            foreign = Subject(user_id=self.second_user_id, name='Чужой предмет')
            db.add_all([owned, foreign])
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            handle_telegram_update(db, self._update('Предметная задача'))
            subject_prompt = handle_telegram_update(
                db,
                self._callback('add_task_deadline_none'),
            )
            confirmation = handle_telegram_update(
                db,
                self._callback(f'add_task_subject:{foreign.id}'),
            )

            rendered_buttons = [
                button['text']
                for row in subject_prompt.reply_markup['inline_keyboard']
                for button in row
            ]
            self.assertIn('Python', rendered_buttons)
            self.assertNotIn('Чужой предмет', rendered_buttons)
            self.assertIn('Выбери приоритет', confirmation.text)

            final = handle_telegram_update(
                db,
                self._callback('add_task_priority_medium'),
            )
            self.assertIn('Предмет не найден', final.text)

    def test_add_task_dialog_cancel_and_cancel_command_clear_state(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            cancelled = handle_telegram_update(
                db,
                self._callback('add_task_cancel'),
            )
            no_action = handle_telegram_update(db, self._update('/cancel'))

            self.assertIn('Добавление задачи отменено', cancelled.text)
            self.assertIn('нет активного действия', no_action.text)

            handle_telegram_update(db, self._update('/add_task'))
            command_cancelled = handle_telegram_update(db, self._update('/cancel'))
            fresh = handle_telegram_update(db, self._update('/add_task'))

            self.assertIn('Действие отменено', command_cancelled.text)
            self.assertIn('<b>Новая задача</b>', fresh.text)

    def test_add_task_dialog_prompts_before_restarting_active_flow(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('/add_task'))
            handle_telegram_update(db, self._update('Незавершённая задача'))
            repeated = handle_telegram_update(db, self._update('/add_task'))
            continued = handle_telegram_update(
                db,
                self._callback('add_task_continue'),
            )
            restarted = handle_telegram_update(
                db,
                self._callback('add_task_restart'),
            )

            self.assertIn('Есть незавершённая задача', repeated.text)
            self.assertIn('Когда дедлайн', continued.text)
            self.assertIn('Новая задача', restarted.text)

    def test_plain_text_offers_quick_task_and_creates_it(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            offer = handle_telegram_update(
                db,
                self._update('Сделать доклад по философии'),
            )
            created = handle_telegram_update(
                db,
                self._callback('add_task_quick_create'),
            )

            task = db.query(Task).one()
            self.assertIn('Добавить это как задачу?', offer.text)
            self.assertIn('Сделать доклад по философии', offer.text)
            self.assertIn('Задача добавлена', created.text)
            self.assertEqual(task.title, 'Сделать доклад по философии')
            self.assertIsNone(task.deadline)
            self.assertEqual(task.priority, 'medium')

    def test_plain_text_customize_goes_directly_to_deadline(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            handle_telegram_update(db, self._update('Настраиваемая задача'))
            deadline = handle_telegram_update(
                db,
                self._callback('add_task_quick_customize'),
            )

            self.assertIn('Когда дедлайн', deadline.text)

    def test_telegram_deadline_parser_supports_relative_and_iso_formats(self):
        now = datetime(2026, 6, 13, 12, 0)

        today, today_ok = parse_telegram_deadline('сегодня', now=now)
        tomorrow, tomorrow_ok = parse_telegram_deadline('завтра 18:00', now=now)
        iso_date, iso_date_ok = parse_telegram_deadline('2026-07-01', now=now)
        iso_time, iso_time_ok = parse_telegram_deadline('2026-07-01 09:30', now=now)
        russian_date, russian_date_ok = parse_telegram_deadline('15.06.2026', now=now)
        invalid, invalid_ok = parse_telegram_deadline('после сессии', now=now)

        self.assertTrue(today_ok)
        self.assertEqual(today, datetime(2026, 6, 13, 23, 59))
        self.assertTrue(tomorrow_ok)
        self.assertEqual(tomorrow, datetime(2026, 6, 14, 18, 0))
        self.assertTrue(iso_date_ok)
        self.assertEqual(iso_date, datetime(2026, 7, 1, 23, 59))
        self.assertTrue(iso_time_ok)
        self.assertEqual(iso_time, datetime(2026, 7, 1, 9, 30))
        self.assertTrue(russian_date_ok)
        self.assertEqual(russian_date, datetime(2026, 6, 15, 23, 59))
        self.assertFalse(invalid_ok)
        self.assertIsNone(invalid)

    def test_today_uses_only_current_users_schedule(self):
        with self.SessionLocal() as db:
            first = db.get(User, self.first_user_id)
            second = db.get(User, self.second_user_id)
            first.telegram_user_id = 7001
            first.telegram_chat_id = 8001
            first_subject = Subject(user_id=first.id, name='Visible subject')
            second_subject = Subject(user_id=second.id, name='Private subject')
            db.add_all([first_subject, second_subject])
            db.flush()
            db.add_all(
                [
                    ScheduleItem(
                        user_id=first.id,
                        subject_id=first_subject.id,
                        weekday=current_date().weekday(),
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                    ),
                    ScheduleItem(
                        user_id=second.id,
                        subject_id=second_subject.id,
                        weekday=current_date().weekday(),
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                ]
            )
            db.commit()

            reply = handle_telegram_update(db, self._update('/today'))

            self.assertIn('Visible subject', reply.text)
            self.assertNotIn('Private subject', reply.text)

    def test_done_requires_linked_account_and_argument(self):
        with self.SessionLocal() as db:
            unlinked = handle_telegram_update(db, self._update('/done 1'))
            self.assertIn('Аккаунт не подключён', unlinked.text)

            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            instruction = handle_telegram_update(db, self._update('/done'))
            self.assertIn('<b>Закрытие задачи</b>', instruction.text)
            self.assertIn('<code>/done 1</code>', instruction.text)

    def test_done_by_list_number_completes_only_owned_task(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            owned = Task(
                user_id=user.id,
                title='Закрыть через Telegram',
                deadline=current_time() + timedelta(hours=1),
                is_completed=False,
            )
            foreign = Task(
                user_id=self.second_user_id,
                title='Чужая задача',
                deadline=current_time(),
                is_completed=False,
            )
            db.add_all([owned, foreign])
            db.commit()

            reply = handle_telegram_update(db, self._update('/done 1'))
            db.refresh(owned)
            db.refresh(foreign)
            remaining = handle_telegram_update(db, self._update('/tasks'))

            self.assertIn('Задача выполнена', reply.text)
            self.assertIn('Закрыть через Telegram', reply.text)
            self.assertTrue(owned.is_completed)
            self.assertIsNotNone(owned.completed_at)
            self.assertFalse(foreign.is_completed)
            self.assertNotIn('Закрыть через Telegram', remaining.text)

    def test_done_rejects_wrong_number_and_foreign_task_id(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            foreign = Task(
                user_id=self.second_user_id,
                title='Недоступная задача',
                is_completed=False,
            )
            db.add(foreign)
            db.commit()

            wrong = handle_telegram_update(db, self._update('/done не-номер'))
            unavailable = handle_telegram_update(
                db,
                self._callback(f'done_task:{foreign.id}'),
            )
            db.refresh(foreign)

            self.assertIn('Задача не найдена', wrong.text)
            self.assertIn('Задача не найдена', unavailable.text)
            self.assertFalse(foreign.is_completed)

    def test_tasks_include_secure_done_buttons_and_callback_completes_task(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            task = Task(
                user_id=user.id,
                title='<Закрыть & проверить>',
                deadline=current_time() + timedelta(hours=1),
                is_completed=False,
            )
            db.add(task)
            db.commit()

            tasks_reply = handle_telegram_update(db, self._update('/tasks'))
            callback_data = tasks_reply.reply_markup['inline_keyboard'][0][0][
                'callback_data'
            ]
            completed = handle_telegram_update(db, self._callback(callback_data))
            db.refresh(task)

            self.assertEqual(callback_data, f'done_task:{task.id}')
            self.assertIn('✅ Закрыть 1', tasks_reply.reply_markup['inline_keyboard'][0][0]['text'])
            self.assertIn('&lt;Закрыть &amp; проверить&gt;', completed.text)
            self.assertEqual(completed.callback_query_id, f'callback-{callback_data}')
            self.assertTrue(task.is_completed)

    def test_done_callback_reports_already_completed_task(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            task = Task(
                user_id=user.id,
                title='Уже готово',
                is_completed=True,
                completed_at=current_time(),
            )
            db.add(task)
            db.commit()

            reply = handle_telegram_update(
                db,
                self._callback(f'done_task:{task.id}'),
            )

            self.assertIn('уже выполнена', reply.text)

    def test_tomorrow_requires_link_and_has_empty_state(self):
        with self.SessionLocal() as db:
            unlinked = handle_telegram_update(db, self._update('/tomorrow'))
            self.assertIn('Аккаунт не подключён', unlinked.text)

            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            empty = handle_telegram_update(db, self._update('/tomorrow'))
            self.assertIn('<b>Завтра</b>', empty.text)
            self.assertIn('На завтра ничего не запланировано', empty.text)
            self.assertNotIn('<b>Пары</b>', empty.text)

    def test_tomorrow_shows_owned_schedule_tasks_and_events(self):
        tomorrow = current_date() + timedelta(days=1)
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            subject = Subject(user_id=user.id, name='Математика')
            private_subject = Subject(user_id=self.second_user_id, name='Чужой предмет')
            db.add_all([subject, private_subject])
            db.flush()
            db.add_all(
                [
                    ScheduleItem(
                        user_id=user.id,
                        subject_id=subject.id,
                        weekday=tomorrow.weekday(),
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                        room='302',
                    ),
                    ScheduleItem(
                        user_id=self.second_user_id,
                        subject_id=private_subject.id,
                        weekday=tomorrow.weekday(),
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                    Task(
                        user_id=user.id,
                        title='Сдать практику',
                        deadline=datetime.combine(tomorrow, time(23, 59)),
                        priority='high',
                        is_completed=False,
                    ),
                    AcademicEvent(
                        user_id=user.id,
                        title='Консультация',
                        event_date=tomorrow,
                        start_time=time(15, 0),
                    ),
                ]
            )
            db.commit()

            reply = handle_telegram_update(db, self._update('/tomorrow'))

            self.assertIn('Математика', reply.text)
            self.assertIn('Аудитория: 302', reply.text)
            self.assertIn('Сдать практику', reply.text)
            self.assertIn('Консультация', reply.text)
            self.assertNotIn('Чужой предмет', reply.text)

    def test_week_requires_link_and_has_empty_state(self):
        with self.SessionLocal() as db:
            unlinked = handle_telegram_update(db, self._update('/week'))
            self.assertIn('Аккаунт не подключён', unlinked.text)

            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            empty = handle_telegram_update(db, self._update('/week'))
            self.assertIn('<b>Ближайшая неделя</b>', empty.text)
            self.assertIn('пока ничего не запланировано', empty.text)

    def test_week_is_compact_sorted_and_limited_to_five_deadlines(self):
        start = current_date()
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            subject = Subject(user_id=user.id, name='Физика')
            db.add(subject)
            db.flush()
            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=subject.id,
                    weekday=start.weekday(),
                    start_time=time(10, 0),
                    end_time=time(11, 30),
                )
            )
            for index in range(6):
                db.add(
                    Task(
                        user_id=user.id,
                        title=f'Дедлайн {index + 1}',
                        deadline=datetime.combine(
                            start + timedelta(days=index),
                            time(18, 0),
                        ),
                        priority='high' if index == 0 else 'medium',
                        is_completed=False,
                    )
                )
            db.add(
                Task(
                    user_id=self.second_user_id,
                    title='Чужой недельный дедлайн',
                    deadline=datetime.combine(start, time(12, 0)),
                    is_completed=False,
                )
            )
            db.commit()

            reply = handle_telegram_update(db, self._update('/week'))

            self.assertIn('<b>Кратко по дням</b>', reply.text)
            self.assertIn('1 пара', reply.text)
            self.assertIn('Дедлайн 1', reply.text)
            self.assertIn('Дедлайн 5', reply.text)
            self.assertNotIn('Дедлайн 6', reply.text)
            self.assertNotIn('Чужой недельный дедлайн', reply.text)

    def test_site_and_unlink_commands(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            site_reply = handle_telegram_update(db, self._update('/site'))
            unlink_reply = handle_telegram_update(db, self._update('/unlink'))
            db.refresh(user)

            self.assertIn('Student Assistant', site_reply.text)
            self.assertTrue(
                site_reply.reply_markup['inline_keyboard'][0][0]['url'].startswith('http')
            )
            self.assertIn('Отключить Telegram?', unlink_reply.text)
            self.assertEqual(
                unlink_reply.reply_markup['inline_keyboard'][0][0]['callback_data'],
                'unlink_confirm',
            )
            self.assertEqual(user.telegram_user_id, 7001)

            confirmed = handle_telegram_update(db, self._callback('unlink_confirm'))
            db.refresh(user)

            self.assertIn('Telegram отключён', confirmed.text)
            self.assertIsNone(user.telegram_user_id)

    def test_unlink_cancel_keeps_account_connected(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            reply = handle_telegram_update(db, self._callback('unlink_cancel'))
            db.refresh(user)

            self.assertIn('Telegram остаётся подключён', reply.text)
            self.assertEqual(reply.callback_query_id, 'callback-unlink_cancel')
            self.assertEqual(user.telegram_user_id, 7001)

    def test_callback_buttons_reuse_today_tasks_help_and_site_actions(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            today = handle_telegram_update(db, self._callback('today'))
            tomorrow = handle_telegram_update(db, self._callback('tomorrow'))
            week = handle_telegram_update(db, self._callback('week'))
            tasks = handle_telegram_update(db, self._callback('tasks'))
            help_reply = handle_telegram_update(db, self._callback('help'))
            add_task = handle_telegram_update(db, self._callback('add_task_start'))
            site = handle_telegram_update(db, self._callback('site'))

            self.assertIn('<b>Сегодня</b>', today.text)
            self.assertIn('<b>Завтра</b>', tomorrow.text)
            self.assertIn('<b>Ближайшая неделя</b>', week.text)
            self.assertIn('<b>Ближайшие задачи</b>', tasks.text)
            self.assertIn('<b>Команды Student Assistant</b>', help_reply.text)
            self.assertIn('<b>Новая задача</b>', add_task.text)
            self.assertIn('<b>Student Assistant</b>', site.text)
            self.assertEqual(today.callback_query_id, 'callback-today')
            self.assertEqual(today.chat_action, 'typing')

            start = handle_telegram_update(db, self._update('/start'))
            start_callbacks = [
                button.get('callback_data')
                for row in start.reply_markup['inline_keyboard']
                for button in row
            ]
            self.assertIn('add_task_start', start_callbacks)
            self.assertIn('tomorrow', start_callbacks)
            self.assertIn('week', start_callbacks)

    def test_html_user_and_task_data_is_escaped(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.display_name = '<Лёля & друзья>'
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.add(
                Task(
                    user_id=user.id,
                    title='<Отчёт & практика>',
                    is_completed=False,
                    priority='high',
                )
            )
            db.commit()

            start_reply = handle_telegram_update(db, self._update('/start'))
            tasks_reply = handle_telegram_update(db, self._update('/tasks'))

            self.assertIn('&lt;Лёля &amp; друзья&gt;', start_reply.text)
            self.assertNotIn('<Лёля & друзья>', start_reply.text)
            self.assertIn('&lt;Отчёт &amp; практика&gt;', tasks_reply.text)

    def test_unknown_text_has_compact_help_buttons(self):
        with self.SessionLocal() as db:
            reply = handle_telegram_update(db, self._update('что ты умеешь?'))

        self.assertIn('Аккаунт не подключён', reply.text)

    def test_message_builders_have_consistent_polish(self):
        user = SimpleNamespace(display_name='Лёля', username='telegram-first')

        self.assertIn(MESSAGE_DIVIDER, build_start_unlinked_message())
        self.assertIn(MESSAGE_DIVIDER, build_start_linked_message(user))
        self.assertIn(MESSAGE_DIVIDER, build_help_message())
        self.assertIn(MESSAGE_DIVIDER, build_link_success_message())
        self.assertIn('Личный кабинет студента', build_site_message())
        self.assertIn('Отключить Telegram?', build_unlink_confirm_message())
        self.assertIn('Я пока не понял команду', build_unknown_command_message())
        self.assertIn('<code>/tomorrow</code>', build_help_message())
        self.assertIn('<code>/week</code>', build_help_message())
        self.assertIn('<code>/done</code>', build_help_message())

    def test_tasks_use_priority_markers_and_polished_footer(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            db.add_all(
                [
                    Task(
                        user_id=user.id,
                        title='Высокий приоритет',
                        deadline=current_time() + timedelta(hours=1),
                        priority='high',
                        is_completed=False,
                    ),
                    Task(
                        user_id=user.id,
                        title='Средний приоритет',
                        deadline=current_time() + timedelta(hours=2),
                        priority='medium',
                        is_completed=False,
                    ),
                    Task(
                        user_id=user.id,
                        title='Низкий приоритет',
                        priority='low',
                        is_completed=False,
                    ),
                ]
            )
            db.commit()

            message = build_tasks_message(db, user)

        self.assertIn('🔴 высокий', message)
        self.assertIn('🟡 средний', message)
        self.assertIn('🟢 низкий', message)
        self.assertIn('без даты', message)
        self.assertIn('Показываю только ближайшие активные задачи.', message)

    def test_send_message_uses_html_keyboard_and_acknowledges_callback(self):
        reply = TelegramReply(
            chat_id=8001,
            text='<b>Красивый ответ</b>',
            reply_markup={
                'inline_keyboard': [[{'text': '📅 Сегодня', 'callback_data': 'today'}]]
            },
            callback_query_id='callback-1',
        )
        with patch('app.services.telegram_bot.call_telegram_api') as api_call:
            send_telegram_message(reply)

        self.assertEqual(api_call.call_count, 2)
        api_call.assert_any_call(
            'answerCallbackQuery',
            {'callback_query_id': 'callback-1'},
        )
        api_call.assert_any_call(
            'sendMessage',
            {
                'chat_id': 8001,
                'text': '<b>Красивый ответ</b>',
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
                'reply_markup': reply.reply_markup,
            },
        )

    def test_send_message_shows_typing_for_important_reply(self):
        reply = TelegramReply(
            chat_id=8001,
            text='<b>Сегодня</b>',
            chat_action='typing',
        )
        with patch('app.services.telegram_bot.call_telegram_api') as api_call:
            send_telegram_message(reply)

        self.assertEqual(api_call.call_count, 2)
        api_call.assert_any_call(
            'sendChatAction',
            {'chat_id': 8001, 'action': 'typing'},
        )

    def test_webhook_rejects_wrong_secret_and_handles_valid_update(self):
        route_settings = SimpleNamespace(
            telegram_webhook_secret='test-webhook-secret',
            telegram_bot_token='',
        )
        webhook_path = settings.telegram_webhook_path

        with patch('app.web.routes.telegram.settings', route_settings):
            rejected = self.client.post(
                f'{webhook_path}/wrong-secret',
                json=self._update('/start'),
            )
            accepted = self.client.post(
                f'{webhook_path}/test-webhook-secret',
                json=self._update('/start'),
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json(), {'ok': True})

    def test_profile_template_contains_telegram_controls(self):
        self._login()
        disconnected_response = self.client.get('/profile')
        self.assertEqual(disconnected_response.status_code, 200)
        self.assertIn('Telegram-бот', disconnected_response.text)
        self.assertIn('/profile/telegram/link-code', disconnected_response.text)
        self.assertIn('Подключить Telegram', disconnected_response.text)
        self.assertIn('Telegram не подключён', disconnected_response.text)
        self.assertIn('Напоминания о дедлайнах', disconnected_response.text)

        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()
        response = self.client.get('/profile')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Утренняя сводка', response.text)
        self.assertIn('Напоминания о дедлайнах', response.text)
        self.assertIn('/profile/telegram/notification-settings', response.text)
        self.assertIn('Открыть бота', response.text)

    def test_digest_message_contains_today_counts_nearest_lesson_and_safe_tasks(self):
        target_date = date(2026, 6, 15)
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            subject = Subject(user_id=user.id, name='Теория <систем>')
            db.add(subject)
            db.flush()
            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=subject.id,
                    weekday=target_date.weekday(),
                    start_time=time(9, 0),
                    end_time=time(10, 30),
                    room='А-10',
                )
            )
            db.add_all(
                [
                    Task(
                        user_id=user.id,
                        title='Сдать <эссе>',
                        deadline=datetime(2026, 6, 15, 18, 0),
                        priority='high',
                        is_completed=False,
                    ),
                    Task(
                        user_id=user.id,
                        title='Повторить конспект',
                        deadline=datetime(2026, 6, 16, 12, 0),
                        priority='medium',
                        is_completed=False,
                    ),
                    Task(
                        user_id=user.id,
                        title='Уже готово',
                        deadline=datetime(2026, 6, 15, 10, 0),
                        is_completed=True,
                    ),
                ]
            )
            db.commit()

            message = build_morning_digest_message(
                db,
                user,
                target_date=target_date,
                current_local_time=time(8, 0),
            )

        self.assertIn('Доброе утро, Лёля!', message)
        self.assertIn('Пар: <b>1</b>', message)
        self.assertIn('Активных задач: <b>2</b>', message)
        self.assertIn('Дедлайнов сегодня: <b>1</b>', message)
        self.assertIn('Ближайшая пара', message)
        self.assertIn('09:00–10:30', message)
        self.assertIn('Теория &lt;систем&gt;', message)
        self.assertIn('Сдать &lt;эссе&gt;', message)
        self.assertNotIn('Уже готово', message)

    def test_digest_commands_toggle_settings_and_send_test_without_marking_date(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            settings_reply = handle_telegram_update(db, self._update('/digest'))
            self.assertIn('выключена', settings_reply.text)
            callback_settings_reply = handle_telegram_update(
                db,
                self._callback('digest'),
            )
            self.assertEqual(
                callback_settings_reply.callback_query_id,
                'callback-digest',
            )

            enabled_reply = handle_telegram_update(
                db,
                self._callback('digest_on'),
            )
            db.refresh(user)
            self.assertTrue(user.telegram_morning_digest_enabled)
            self.assertEqual(user.telegram_morning_digest_time, time(8, 0))
            self.assertIn('Утренняя сводка включена ✅', enabled_reply.text)
            self.assertEqual(enabled_reply.callback_query_id, 'callback-digest_on')
            self.assertIn('включена', enabled_reply.text)

            test_reply = handle_telegram_update(
                db,
                self._callback('digest_test'),
            )
            db.refresh(user)
            self.assertIn('Доброе утро', test_reply.text)
            self.assertEqual(test_reply.callback_query_id, 'callback-digest_test')
            self.assertIsNone(user.telegram_morning_digest_last_sent_date)

            disabled_reply = handle_telegram_update(
                db,
                self._callback('digest_off'),
            )
            db.refresh(user)
            self.assertFalse(user.telegram_morning_digest_enabled)
            self.assertIn('Утренняя сводка выключена.', disabled_reply.text)
            self.assertEqual(disabled_reply.callback_query_id, 'callback-digest_off')

        self.assertIn('Часовой пояс', build_digest_settings_message(user))

    def test_digest_requires_linked_account(self):
        with self.SessionLocal() as db:
            command_reply = handle_telegram_update(db, self._update('/digest'))
            callback_reply = handle_telegram_update(
                db,
                self._callback('digest_on'),
            )

        self.assertIn('Аккаунт не подключён', command_reply.text)
        self.assertIn('Аккаунт не подключён', callback_reply.text)
        self.assertEqual(callback_reply.callback_query_id, 'callback-digest_on')

    def test_digest_empty_state_is_clear(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            message = build_morning_digest_message(
                db,
                user,
                target_date=date(2026, 6, 15),
                current_local_time=time(8, 0),
            )

        self.assertIn('На сегодня ничего не запланировано ✅', message)
        self.assertIn('Хорошего учебного дня', message)

    def test_digest_profile_settings_and_test_send(self):
        self._login()
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

        csrf = self._csrf(self.client.get('/profile').text)
        response = self.client.post(
            '/profile/telegram/digest-settings',
            data={
                'csrf_token': csrf,
                'digest_enabled': 'on',
                'digest_time': '07:30',
                'digest_timezone': 'Asia/Yekaterinburg',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('telegram_status=digest-saved', response.headers['location'])

        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            self.assertTrue(user.telegram_morning_digest_enabled)
            self.assertEqual(user.telegram_morning_digest_time, time(7, 30))
            self.assertEqual(
                user.telegram_morning_digest_timezone,
                'Asia/Yekaterinburg',
            )

        with patch('app.web.routes.profile.send_telegram_message') as send:
            response = self.client.post(
                '/profile/telegram/digest-test',
                data={'csrf_token': csrf},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn('telegram_status=digest-test-sent', response.headers['location'])
        sent_reply = send.call_args.args[0]
        self.assertEqual(sent_reply.chat_id, 8001)
        self.assertIn('Доброе утро', sent_reply.text)

    def test_notification_profile_settings_validate_and_save_for_current_user(self):
        self._login()
        with self.SessionLocal() as db:
            first = db.get(User, self.first_user_id)
            second = db.get(User, self.second_user_id)
            first.telegram_user_id = 7001
            first.telegram_chat_id = 8001
            second.telegram_deadline_reminders_enabled = False
            second.telegram_deadline_reminder_hours = 24
            db.commit()

        csrf = self._csrf(self.client.get('/profile').text)
        response = self.client.post(
            '/profile/telegram/notification-settings',
            data={
                'csrf_token': csrf,
                'digest_enabled': 'on',
                'digest_time': '08:00',
                'digest_timezone': 'Europe/Moscow',
                'deadline_enabled': 'on',
                'deadline_hours': '6',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('telegram_status=notifications-saved', response.headers['location'])
        with self.SessionLocal() as db:
            first = db.get(User, self.first_user_id)
            second = db.get(User, self.second_user_id)
            self.assertTrue(first.telegram_morning_digest_enabled)
            self.assertEqual(first.telegram_morning_digest_time, time(8, 0))
            self.assertTrue(first.telegram_deadline_reminders_enabled)
            self.assertEqual(first.telegram_deadline_reminder_hours, 6)
            self.assertFalse(second.telegram_deadline_reminders_enabled)
            self.assertEqual(second.telegram_deadline_reminder_hours, 24)

        for invalid_data in (
            {
                'digest_time': '28:90',
                'digest_timezone': 'Europe/Moscow',
                'deadline_hours': '6',
            },
            {
                'digest_time': '08:00',
                'digest_timezone': 'Europe/Moscow',
                'deadline_hours': '3',
            },
        ):
            response = self.client.post(
                '/profile/telegram/notification-settings',
                data={'csrf_token': csrf, **invalid_data},
                follow_redirects=False,
            )
            self.assertIn(
                'telegram_status=notifications-error',
                response.headers['location'],
            )

    def test_notification_profile_settings_require_telegram_link(self):
        self._login()
        csrf = self._csrf(self.client.get('/profile').text)
        response = self.client.post(
            '/profile/telegram/notification-settings',
            data={
                'csrf_token': csrf,
                'digest_time': '08:00',
                'digest_timezone': 'Europe/Moscow',
                'deadline_enabled': 'on',
                'deadline_hours': '24',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            'telegram_status=notifications-not-linked',
            response.headers['location'],
        )

    def test_notifications_command_and_callbacks_manage_current_user_settings(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()

            settings_reply = handle_telegram_update(
                db,
                self._update('/notifications'),
            )
            self.assertIn('Telegram-уведомления', settings_reply.text)
            self.assertIn('Дедлайны: <b>выключены</b>', settings_reply.text)

            digest_reply = handle_telegram_update(
                db,
                self._callback('digest_toggle'),
            )
            deadline_reply = handle_telegram_update(
                db,
                self._callback('deadline_toggle'),
            )
            hours_reply = handle_telegram_update(
                db,
                self._callback('deadline_hours:2'),
            )
            db.refresh(user)

            self.assertTrue(user.telegram_morning_digest_enabled)
            self.assertTrue(user.telegram_deadline_reminders_enabled)
            self.assertEqual(user.telegram_deadline_reminder_hours, 2)
            self.assertEqual(digest_reply.callback_query_id, 'callback-digest_toggle')
            self.assertEqual(
                deadline_reply.callback_query_id,
                'callback-deadline_toggle',
            )
            self.assertEqual(
                hours_reply.callback_query_id,
                'callback-deadline_hours:2',
            )
            self.assertIn('примерно за 2 ч.', hours_reply.text)
            self.assertIn('Напоминать за: <b>2 ч.</b>', hours_reply.text)

        self.assertIn('Утренняя сводка', build_notifications_settings_message(user))

    def test_notifications_requires_linked_account(self):
        with self.SessionLocal() as db:
            reply = handle_telegram_update(db, self._update('/notifications'))
            callback_reply = handle_telegram_update(
                db,
                self._callback('deadline_toggle'),
            )

        self.assertIn('Аккаунт не подключён', reply.text)
        self.assertIn('Аккаунт не подключён', callback_reply.text)
        self.assertEqual(
            callback_reply.callback_query_id,
            'callback-deadline_toggle',
        )

    def test_digest_scheduler_sends_once_per_local_day(self):
        now_utc = datetime(2026, 6, 15, 5, 5, tzinfo=UTC)
        sent = []
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            user.telegram_morning_digest_enabled = True
            user.telegram_morning_digest_time = time(8, 0)
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.commit()

            first_count = scheduler.process_due_digests(
                db,
                now_utc=now_utc,
                send_message=sent.append,
            )
            second_count = scheduler.process_due_digests(
                db,
                now_utc=now_utc,
                send_message=sent.append,
            )
            db.refresh(user)

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(
                user.telegram_morning_digest_last_sent_date,
                date(2026, 6, 15),
            )

    def test_digest_scheduler_skips_disabled_unlinked_and_early_users(self):
        now_utc = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        sent = []
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_morning_digest_time = time(8, 0)
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.commit()
            self.assertFalse(scheduler.is_digest_due(user, now_utc))
            self.assertEqual(
                scheduler.process_due_digests(
                    db,
                    now_utc=now_utc,
                    send_message=sent.append,
                ),
                0,
            )

            user.telegram_morning_digest_enabled = True
            db.commit()
            self.assertFalse(scheduler.is_digest_due(user, now_utc))
            self.assertEqual(
                scheduler.process_due_digests(
                    db,
                    now_utc=now_utc,
                    send_message=sent.append,
                ),
                0,
            )

            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()
            self.assertFalse(scheduler.is_digest_due(user, now_utc))

            user.telegram_morning_digest_time = time(7, 0)
            db.commit()
            self.assertTrue(scheduler.is_digest_due(user, now_utc))

            user.telegram_morning_digest_enabled = False
            db.commit()
            self.assertFalse(scheduler.is_digest_due(user, now_utc))
            self.assertEqual(sent, [])

    def test_digest_scheduler_retries_after_delivery_error(self):
        now_utc = datetime(2026, 6, 15, 5, 5, tzinfo=UTC)
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            user.telegram_morning_digest_enabled = True
            user.telegram_morning_digest_time = time(8, 0)
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.commit()

            sent_count = scheduler.process_due_digests(
                db,
                now_utc=now_utc,
                send_message=lambda _: (_ for _ in ()).throw(RuntimeError('failed')),
            )
            db.refresh(user)

            self.assertEqual(sent_count, 0)
            self.assertIsNone(user.telegram_morning_digest_last_sent_date)

    def test_deadline_scheduler_sends_once_to_task_owner(self):
        now_utc = datetime(2026, 6, 15, 5, 0, tzinfo=UTC)
        sent = []
        with self.SessionLocal() as db:
            first = db.get(User, self.first_user_id)
            second = db.get(User, self.second_user_id)
            first.telegram_user_id = 7001
            first.telegram_chat_id = 8001
            first.telegram_morning_digest_timezone = 'Europe/Moscow'
            first.telegram_deadline_reminders_enabled = True
            first.telegram_deadline_reminder_hours = 6
            db.add_all(
                [
                    Task(
                        user_id=first.id,
                        title='Сдать <лабораторную>',
                        deadline=datetime(2026, 6, 15, 14, 0),
                        priority='high',
                        is_completed=False,
                    ),
                    Task(
                        user_id=second.id,
                        title='Чужая задача',
                        deadline=datetime(2026, 6, 15, 13, 0),
                        is_completed=False,
                    ),
                ]
            )
            db.commit()

            first_count = scheduler.process_deadline_reminders(
                db,
                now_utc=now_utc,
                send_message=sent.append,
            )
            second_count = scheduler.process_deadline_reminders(
                db,
                now_utc=now_utc,
                send_message=sent.append,
            )

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].chat_id, 8001)
            self.assertIn('Сдать &lt;лабораторную&gt;', sent[0].text)
            self.assertNotIn('Чужая задача', sent[0].text)
            callbacks = [
                button.get('callback_data')
                for row in sent[0].reply_markup['inline_keyboard']
                for button in row
                if button.get('callback_data')
            ]
            self.assertIn('tasks', callbacks)
            self.assertTrue(any(value.startswith('done_task:') for value in callbacks))
            self.assertEqual(db.query(TelegramDeadlineReminderLog).count(), 1)

    def test_deadline_scheduler_skips_disabled_unlinked_completed_and_undated(self):
        now_utc = datetime(2026, 6, 15, 5, 0, tzinfo=UTC)
        sent = []
        with self.SessionLocal() as db:
            user = db.get(User, self.first_user_id)
            user.telegram_deadline_reminder_hours = 6
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.add_all(
                [
                    Task(
                        user_id=user.id,
                        title='Completed',
                        deadline=datetime(2026, 6, 15, 13, 0),
                        is_completed=True,
                    ),
                    Task(
                        user_id=user.id,
                        title='Undated',
                        deadline=None,
                        is_completed=False,
                    ),
                ]
            )
            db.commit()

            self.assertEqual(
                scheduler.process_deadline_reminders(
                    db,
                    now_utc=now_utc,
                    send_message=sent.append,
                ),
                0,
            )

            user.telegram_deadline_reminders_enabled = True
            db.commit()
            self.assertEqual(
                scheduler.process_deadline_reminders(
                    db,
                    now_utc=now_utc,
                    send_message=sent.append,
                ),
                0,
            )

            user.telegram_user_id = 7001
            user.telegram_chat_id = 8001
            db.commit()
            self.assertEqual(
                scheduler.process_deadline_reminders(
                    db,
                    now_utc=now_utc,
                    send_message=sent.append,
                ),
                0,
            )
            self.assertEqual(sent, [])

    def test_polling_module_import_does_not_start_loop(self):
        self.assertTrue(callable(polling.main))
        self.assertTrue(callable(polling.run_polling))
        self.assertTrue(callable(scheduler.main))
        self.assertTrue(callable(scheduler.run_scheduler))

    def test_get_updates_uses_long_polling_offset(self):
        api_response = {
            'ok': True,
            'result': [{'update_id': 42, 'message': {}}],
        }
        with patch(
            'app.services.telegram_bot.call_telegram_api',
            return_value=api_response,
        ) as api_call:
            updates = get_telegram_updates(offset=40, timeout=25)

        self.assertEqual(updates, api_response['result'])
        api_call.assert_called_once_with(
            'getUpdates',
            {
                'timeout': 25,
                'allowed_updates': ['message', 'callback_query'],
                'offset': 40,
            },
            request_timeout=35,
        )

    def test_install_commands_syncs_all_task_and_planning_commands(self):
        with patch('app.services.telegram_bot.call_telegram_api') as api_call:
            install_telegram_commands()

        api_call.assert_called_once_with(
            'setMyCommands',
            {'commands': BOT_COMMANDS},
        )
        self.assertIn(
            {'command': 'add_task', 'description': 'Добавить задачу'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'done', 'description': 'Закрыть задачу'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'tomorrow', 'description': 'Планы на завтра'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'week', 'description': 'Обзор недели'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'cancel', 'description': 'Отменить действие'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'digest', 'description': 'Настройки утренней сводки'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'digest_test', 'description': 'Проверить утреннюю сводку'},
            BOT_COMMANDS,
        )
        self.assertIn(
            {'command': 'notifications', 'description': 'Настройки уведомлений'},
            BOT_COMMANDS,
        )

    def test_polling_advances_offset_even_when_processor_fails(self):
        processed = []

        def processor(update):
            processed.append(update['update_id'])
            if update['update_id'] == 10:
                raise RuntimeError('test failure')

        next_offset = polling.process_updates(
            [{'update_id': 10}, {'update_id': 12}],
            None,
            processor=processor,
        )

        self.assertEqual(processed, [10, 12])
        self.assertEqual(next_offset, 13)

    def test_polling_passes_advanced_offset_to_next_get_updates(self):
        calls = []
        processed = []

        def fetch_updates(*, offset, timeout):
            calls.append((offset, timeout))
            if len(calls) == 1:
                return [{'update_id': 55}]
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            polling.run_polling(
                fetch_updates=fetch_updates,
                processor=lambda update: processed.append(update['update_id']),
                sleep=lambda _: None,
            )

        self.assertEqual(
            calls,
            [
                (None, polling.POLLING_TIMEOUT_SECONDS),
                (56, polling.POLLING_TIMEOUT_SECONDS),
            ],
        )
        self.assertEqual(processed, [55])

    def test_polling_process_update_uses_shared_command_handler(self):
        class FakeSession:
            def __init__(self):
                self.closed = False
                self.rolled_back = False

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        session = FakeSession()
        sent = []
        update = self._update('/help')
        expected_reply = TelegramReply(chat_id=8001, text='shared reply')

        with patch(
            'telegram_bot.polling.handle_telegram_update',
            return_value=expected_reply,
        ) as handler:
            polling.process_update(
                update,
                session_factory=lambda: session,
                send_message=sent.append,
            )

        handler.assert_called_once_with(session, update)
        self.assertEqual(sent, [expected_reply])
        self.assertTrue(session.closed)
        self.assertFalse(session.rolled_back)

    def test_polling_main_requires_token(self):
        local_settings = SimpleNamespace(
            telegram_bot_token='',
            telegram_use_webhook=False,
            telegram_bot_log_level='INFO',
        )
        with patch('telegram_bot.polling.settings', local_settings):
            self.assertEqual(polling.main(), 1)

    def test_polling_main_rejects_webhook_mode(self):
        local_settings = SimpleNamespace(
            telegram_bot_token='test-token',
            telegram_use_webhook=True,
            telegram_bot_log_level='INFO',
        )
        with patch('telegram_bot.polling.settings', local_settings):
            self.assertEqual(polling.main(), 1)

    def test_polling_main_deletes_webhook_and_starts_loop(self):
        local_settings = SimpleNamespace(
            telegram_bot_token='test-token',
            telegram_use_webhook=False,
            telegram_bot_log_level='INFO',
        )
        with (
            patch('telegram_bot.polling.settings', local_settings),
            patch('telegram_bot.polling.run_migrations') as migrations,
            patch('telegram_bot.polling.delete_telegram_webhook') as delete_webhook,
            patch('telegram_bot.polling.run_polling', side_effect=KeyboardInterrupt) as run,
        ):
            result = polling.main()

        self.assertEqual(result, 0)
        migrations.assert_called_once_with()
        delete_webhook.assert_called_once_with()
        run.assert_called_once_with()

    def test_polling_continues_when_delete_webhook_fails(self):
        local_settings = SimpleNamespace(
            telegram_bot_token='test-token',
            telegram_use_webhook=False,
            telegram_bot_log_level='INFO',
        )
        with (
            patch('telegram_bot.polling.settings', local_settings),
            patch('telegram_bot.polling.run_migrations'),
            patch(
                'telegram_bot.polling.delete_telegram_webhook',
                side_effect=TelegramAPIError('test failure'),
            ),
            patch('telegram_bot.polling.run_polling', side_effect=KeyboardInterrupt) as run,
        ):
            result = polling.main()

        self.assertEqual(result, 0)
        run.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
