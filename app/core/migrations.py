from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from .. import models  # noqa: F401
from .database import Base, engine


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    upgrade: Callable[[Connection], None]


def _column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return False
    columns = {column['name'] for column in inspector.get_columns(table_name)}
    return column_name in columns


def _index_exists(connection: Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return False
    indexes = {index['name'] for index in inspector.get_indexes(table_name)}
    return index_name in indexes


def _add_users_schedule_unit(connection: Connection) -> None:
    if _column_exists(connection, 'users', 'schedule_unit'):
        return

    connection.execute(
        text("ALTER TABLE users ADD COLUMN schedule_unit VARCHAR(20) NOT NULL DEFAULT 'class'")
    )


def _add_tasks_recurrence_fields(connection: Connection) -> None:
    statements = {
        'completed_at': 'ALTER TABLE tasks ADD COLUMN completed_at TIMESTAMP',
        'recurrence_group_id': 'ALTER TABLE tasks ADD COLUMN recurrence_group_id INTEGER',
        "recurrence_type": "ALTER TABLE tasks ADD COLUMN recurrence_type VARCHAR(20) NOT NULL DEFAULT 'none'",
        'recurrence_interval_days': 'ALTER TABLE tasks ADD COLUMN recurrence_interval_days INTEGER',
        'scheduled_for_date': 'ALTER TABLE tasks ADD COLUMN scheduled_for_date DATE',
        'schedule_item_id': 'ALTER TABLE tasks ADD COLUMN schedule_item_id INTEGER',
    }

    if 'tasks' not in inspect(connection).get_table_names():
        return

    for column_name, statement in statements.items():
        if not _column_exists(connection, 'tasks', column_name):
            connection.execute(text(statement))

    if not _index_exists(connection, 'tasks', 'ix_tasks_recurrence_group_id'):
        connection.execute(
            text('CREATE INDEX ix_tasks_recurrence_group_id ON tasks (recurrence_group_id)')
        )


def _add_academic_calendar_fields(connection: Connection) -> None:
    if 'users' in inspect(connection).get_table_names() and not _column_exists(connection, 'users', 'last_study_day'):
        connection.execute(text('ALTER TABLE users ADD COLUMN last_study_day DATE'))

    if 'academic_events' not in inspect(connection).get_table_names():
        Base.metadata.tables['academic_events'].create(bind=connection, checkfirst=True)

    if not _index_exists(connection, 'academic_events', 'ix_academic_events_id'):
        connection.execute(text('CREATE INDEX ix_academic_events_id ON academic_events (id)'))

    if not _index_exists(connection, 'academic_events', 'ix_academic_events_user_date'):
        connection.execute(text('CREATE INDEX ix_academic_events_user_date ON academic_events (user_id, event_date)'))


def _add_users_onboarding_fields(connection: Connection) -> None:
    if 'users' not in inspect(connection).get_table_names():
        return

    if not _column_exists(connection, 'users', 'onboarding_completed'):
        connection.execute(
            text(
                'ALTER TABLE users ADD COLUMN '
                'onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE'
            )
        )
    if not _column_exists(connection, 'users', 'onboarding_calendar_opened'):
        connection.execute(
            text(
                'ALTER TABLE users ADD COLUMN '
                'onboarding_calendar_opened BOOLEAN NOT NULL DEFAULT FALSE'
            )
        )

    # Existing populated accounts should not suddenly receive first-run guidance.
    connection.execute(
        text(
            """
            UPDATE users
            SET onboarding_completed = TRUE
            WHERE onboarding_completed = FALSE
              AND (
                EXISTS (SELECT 1 FROM subjects WHERE subjects.user_id = users.id)
                OR EXISTS (SELECT 1 FROM tasks WHERE tasks.user_id = users.id)
                OR EXISTS (SELECT 1 FROM schedule_items WHERE schedule_items.user_id = users.id)
                OR EXISTS (SELECT 1 FROM notes WHERE notes.user_id = users.id)
                OR EXISTS (SELECT 1 FROM academic_events WHERE academic_events.user_id = users.id)
              )
            """
        )
    )


def _add_users_onboarding_chat_fields(connection: Connection) -> None:
    if 'users' not in inspect(connection).get_table_names():
        return

    if not _column_exists(connection, 'users', 'display_name'):
        connection.execute(text('ALTER TABLE users ADD COLUMN display_name VARCHAR(40)'))
    if not _column_exists(connection, 'users', 'onboarding_chat_completed'):
        connection.execute(
            text(
                'ALTER TABLE users ADD COLUMN '
                'onboarding_chat_completed BOOLEAN NOT NULL DEFAULT FALSE'
            )
        )

    connection.execute(
        text(
            """
            UPDATE users
            SET display_name = username
            WHERE display_name IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE users
            SET onboarding_chat_completed = TRUE
            WHERE onboarding_chat_completed = FALSE
              AND (
                onboarding_completed = TRUE
                OR EXISTS (SELECT 1 FROM subjects WHERE subjects.user_id = users.id)
                OR EXISTS (SELECT 1 FROM tasks WHERE tasks.user_id = users.id)
                OR EXISTS (SELECT 1 FROM schedule_items WHERE schedule_items.user_id = users.id)
                OR EXISTS (SELECT 1 FROM notes WHERE notes.user_id = users.id)
                OR EXISTS (SELECT 1 FROM academic_events WHERE academic_events.user_id = users.id)
              )
            """
        )
    )


def _add_users_password_hint(connection: Connection) -> None:
    if 'users' not in inspect(connection).get_table_names():
        return
    if not _column_exists(connection, 'users', 'password_hint'):
        connection.execute(text('ALTER TABLE users ADD COLUMN password_hint VARCHAR(120)'))


MIGRATIONS = [
    Migration(
        version='20260430_01_add_users_schedule_unit',
        description='Add schedule_unit to users.',
        upgrade=_add_users_schedule_unit,
    ),
    Migration(
        version='20260430_02_add_tasks_recurrence_fields',
        description='Add task recurrence and scheduling fields.',
        upgrade=_add_tasks_recurrence_fields,
    ),
    Migration(
        version='20260530_01_add_academic_calendar_fields',
        description='Add academic session events and last study day.',
        upgrade=_add_academic_calendar_fields,
    ),
    Migration(
        version='20260612_01_add_users_onboarding_fields',
        description='Add persistent first-run onboarding state.',
        upgrade=_add_users_onboarding_fields,
    ),
    Migration(
        version='20260612_02_add_users_onboarding_chat_fields',
        description='Add persistent first-run chat and display name.',
        upgrade=_add_users_onboarding_chat_fields,
    ),
    Migration(
        version='20260612_03_add_users_password_hint',
        description='Add optional password hints.',
        upgrade=_add_users_password_hint,
    ),
]


def run_migrations(target_engine: Engine | None = None) -> None:
    active_engine = target_engine or engine
    Base.metadata.create_all(bind=active_engine)

    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        applied_versions = {
            version
            for version in connection.execute(text('SELECT version FROM schema_migrations')).scalars()
        }

        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            migration.upgrade(connection)
            connection.execute(
                text('INSERT INTO schema_migrations (version) VALUES (:version)'),
                {'version': migration.version},
            )
