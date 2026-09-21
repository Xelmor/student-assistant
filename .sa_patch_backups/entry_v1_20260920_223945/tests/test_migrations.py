import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.core.migrations import run_migrations


class MigrationTests(unittest.TestCase):
    def test_migrations_do_not_use_sqlite_only_datetime_type(self):
        migration_source = Path('app/core/migrations.py').read_text(encoding='utf-8')

        self.assertNotIn(' DATETIME', migration_source)

    def test_existing_sqlite_schema_is_upgraded(self):
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        db_path = temp_dir / 'legacy_migration_test.db'
        if db_path.exists():
            db_path.unlink()

        engine = create_engine(f'sqlite:///{db_path.resolve().as_posix()}')

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE users (
                            id INTEGER PRIMARY KEY,
                            username VARCHAR(50) NOT NULL,
                            email VARCHAR(120) NOT NULL,
                            password_hash VARCHAR(255) NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO users (id, username, email, password_hash)
                        VALUES (1, 'legacy-user', 'legacy@example.com', 'hash')
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO users (id, username, email, password_hash)
                        VALUES (2, 'empty-user', 'empty@example.com', 'hash')
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        CREATE TABLE tasks (
                            id INTEGER PRIMARY KEY,
                            user_id INTEGER NOT NULL,
                            title VARCHAR(150) NOT NULL,
                            is_completed BOOLEAN
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO tasks (id, user_id, title, is_completed)
                        VALUES (1, 1, 'Legacy task', FALSE)
                        """
                    )
                )

            run_migrations(engine)

            inspector = inspect(engine)
            user_columns = {column['name'] for column in inspector.get_columns('users')}
            task_columns = {column['name'] for column in inspector.get_columns('tasks')}
            academic_event_columns = {
                column['name'] for column in inspector.get_columns('academic_events')
            }
            reminder_log_columns = {
                column['name']
                for column in inspector.get_columns('telegram_deadline_reminder_logs')
            }
            user_indexes = {
                index['name']: bool(index.get('unique'))
                for index in inspector.get_indexes('users')
            }

            self.assertIn('schedule_unit', user_columns)
            self.assertIn('last_study_day', user_columns)
            self.assertIn('onboarding_completed', user_columns)
            self.assertIn('onboarding_calendar_opened', user_columns)
            self.assertIn('onboarding_chat_completed', user_columns)
            self.assertIn('display_name', user_columns)
            self.assertIn('password_hint', user_columns)
            self.assertIn('telegram_user_id', user_columns)
            self.assertIn('telegram_chat_id', user_columns)
            self.assertIn('telegram_username', user_columns)
            self.assertIn('telegram_link_code', user_columns)
            self.assertIn('telegram_link_code_expires_at', user_columns)
            self.assertIn('telegram_linked_at', user_columns)
            self.assertIn('telegram_morning_digest_enabled', user_columns)
            self.assertIn('telegram_morning_digest_time', user_columns)
            self.assertIn('telegram_morning_digest_timezone', user_columns)
            self.assertIn('telegram_morning_digest_last_sent_date', user_columns)
            self.assertIn('telegram_deadline_reminders_enabled', user_columns)
            self.assertIn('telegram_deadline_reminder_hours', user_columns)
            self.assertEqual(
                reminder_log_columns,
                {
                    'id',
                    'user_id',
                    'task_id',
                    'reminder_hours',
                    'sent_at',
                    'reminder_date_key',
                },
            )
            self.assertIn('completed_at', task_columns)
            self.assertIn('recurrence_group_id', task_columns)
            self.assertIn('recurrence_type', task_columns)
            self.assertIn('recurrence_interval_days', task_columns)
            self.assertIn('scheduled_for_date', task_columns)
            self.assertIn('schedule_item_id', task_columns)
            self.assertIn('event_date', academic_event_columns)
            self.assertIn('event_type', academic_event_columns)
            self.assertTrue(user_indexes['ix_users_telegram_user_id'])
            self.assertTrue(user_indexes['ix_users_telegram_link_code'])

            with engine.begin() as connection:
                versions = set(
                    connection.execute(text('SELECT version FROM schema_migrations')).scalars()
                )
                onboarding_completed = connection.execute(
                    text('SELECT onboarding_completed FROM users WHERE id = 1')
                ).scalar_one()
                populated_chat_completed = connection.execute(
                    text('SELECT onboarding_chat_completed FROM users WHERE id = 1')
                ).scalar_one()
                empty_chat_completed = connection.execute(
                    text('SELECT onboarding_chat_completed FROM users WHERE id = 2')
                ).scalar_one()
                display_name = connection.execute(
                    text('SELECT display_name FROM users WHERE id = 1')
                ).scalar_one()

            self.assertEqual(
                versions,
                {
                    '20260430_01_add_users_schedule_unit',
                    '20260430_02_add_tasks_recurrence_fields',
                    '20260530_01_add_academic_calendar_fields',
                    '20260612_01_add_users_onboarding_fields',
                    '20260612_02_add_users_onboarding_chat_fields',
                    '20260612_03_add_users_password_hint',
                    '20260612_04_add_users_telegram_fields',
                    '20260612_05_ensure_users_telegram_unique_indexes',
                    '20260614_01_add_users_telegram_digest_fields',
                    '20260614_02_add_telegram_deadline_reminders',
                },
            )
            self.assertTrue(onboarding_completed)
            self.assertTrue(populated_chat_completed)
            self.assertFalse(empty_chat_completed)
            self.assertEqual(display_name, 'legacy-user')
        finally:
            engine.dispose()
            if db_path.exists():
                db_path.unlink()
