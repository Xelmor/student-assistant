from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Note, Task, User
from app.web.routes.dashboard import build_streak_state, get_dashboard_notes, get_dashboard_task_counts


class DashboardQueryTests(unittest.TestCase):
    def setUp(self):
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        self.db_path = temp_dir / f'{self._testMethodName}.db'
        if self.db_path.exists():
            self.db_path.unlink()

        self.engine = create_engine(
            f"sqlite:///{self.db_path.resolve().as_posix()}",
            connect_args={'check_same_thread': False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        with self.SessionLocal() as db:
            user = User(
                username='dashboard-user',
                email='dashboard@example.com',
                password_hash='hash',
            )
            db.add(user)
            db.commit()
            self.user_id = user.id

    def tearDown(self):
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_dashboard_task_counts_use_aggregate_filters(self):
        now = datetime(2026, 5, 22, 12, 0)
        with self.SessionLocal() as db:
            db.add_all(
                [
                    Task(user_id=self.user_id, title='pending overdue', is_completed=False, deadline=now - timedelta(hours=1)),
                    Task(user_id=self.user_id, title='pending future', is_completed=False, deadline=now + timedelta(days=2)),
                    Task(user_id=self.user_id, title='pending no deadline', is_completed=False),
                    Task(user_id=self.user_id, title='completed', is_completed=True, completed_at=now - timedelta(days=1)),
                ]
            )
            db.commit()

            counts = get_dashboard_task_counts(db, self.user_id, now)

        self.assertEqual(counts['pending_count'], 3)
        self.assertEqual(counts['completed_count'], 1)
        self.assertEqual(counts['overdue_count'], 1)

    def test_dashboard_notes_prefer_today_over_recent(self):
        now = datetime(2026, 5, 22, 12, 0)
        with self.SessionLocal() as db:
            db.add_all(
                [
                    Note(user_id=self.user_id, title='old-1', created_at=now - timedelta(days=2)),
                    Note(user_id=self.user_id, title='old-2', created_at=now - timedelta(days=3)),
                    Note(user_id=self.user_id, title='today-1', created_at=now - timedelta(hours=1)),
                    Note(user_id=self.user_id, title='today-2', created_at=now - timedelta(hours=2)),
                    Note(user_id=self.user_id, title='today-3', created_at=now - timedelta(hours=3)),
                    Note(user_id=self.user_id, title='today-4', created_at=now - timedelta(hours=4)),
                ]
            )
            db.commit()

            notes, is_recent = get_dashboard_notes(db, self.user_id, now)

        self.assertFalse(is_recent)
        self.assertEqual([note.title for note in notes], ['today-1', 'today-2', 'today-3'])

    def test_build_streak_state_works_from_dates_only(self):
        today = datetime(2026, 5, 22, 12, 0).date()
        streak = build_streak_state(
            [
                today,
                today - timedelta(days=1),
                today - timedelta(days=2),
                today - timedelta(days=5),
            ],
            today,
        )

        self.assertEqual(streak['days'], 3)


if __name__ == '__main__':
    unittest.main()
