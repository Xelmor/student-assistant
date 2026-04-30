import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.core.migrations import run_migrations


class MigrationTests(unittest.TestCase):
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
                        CREATE TABLE tasks (
                            id INTEGER PRIMARY KEY,
                            user_id INTEGER NOT NULL,
                            title VARCHAR(150) NOT NULL,
                            is_completed BOOLEAN
                        )
                        """
                    )
                )

            run_migrations(engine)

            inspector = inspect(engine)
            user_columns = {column['name'] for column in inspector.get_columns('users')}
            task_columns = {column['name'] for column in inspector.get_columns('tasks')}

            self.assertIn('schedule_unit', user_columns)
            self.assertIn('completed_at', task_columns)
            self.assertIn('recurrence_group_id', task_columns)
            self.assertIn('recurrence_type', task_columns)
            self.assertIn('recurrence_interval_days', task_columns)
            self.assertIn('scheduled_for_date', task_columns)
            self.assertIn('schedule_item_id', task_columns)

            with engine.begin() as connection:
                versions = set(
                    connection.execute(text('SELECT version FROM schema_migrations')).scalars()
                )

            self.assertEqual(
                versions,
                {
                    '20260430_01_add_users_schedule_unit',
                    '20260430_02_add_tasks_recurrence_fields',
                },
            )
        finally:
            engine.dispose()
            if db_path.exists():
                db_path.unlink()
