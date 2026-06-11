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
        'completed_at': 'ALTER TABLE tasks ADD COLUMN completed_at DATETIME',
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

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS academic_events (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                subject_id INTEGER,
                title VARCHAR(150) NOT NULL,
                event_type VARCHAR(20) NOT NULL DEFAULT 'exam',
                event_date DATE NOT NULL,
                start_time TIME,
                end_time TIME,
                room VARCHAR(50),
                description TEXT,
                created_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users (id),
                FOREIGN KEY(subject_id) REFERENCES subjects (id)
            )
            """
        )
    )

    if not _index_exists(connection, 'academic_events', 'ix_academic_events_id'):
        connection.execute(text('CREATE INDEX ix_academic_events_id ON academic_events (id)'))

    if not _index_exists(connection, 'academic_events', 'ix_academic_events_user_date'):
        connection.execute(text('CREATE INDEX ix_academic_events_user_date ON academic_events (user_id, event_date)'))


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
