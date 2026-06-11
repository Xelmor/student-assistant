from __future__ import annotations

from datetime import date, time
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import AcademicEvent, ScheduleItem, Subject, User
from app.services.calendar_service import build_calendar_event_map


class CalendarSessionTests(unittest.TestCase):
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

    def tearDown(self):
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_summer_month_uses_session_events_without_weekly_classes(self):
        with self.SessionLocal() as db:
            user = User(username='summer-user', email='summer@example.com', password_hash='hash')
            subject = Subject(user=user, name='ТЕРВЕР')
            db.add_all([user, subject])
            db.flush()
            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=subject.id,
                    weekday=0,
                    start_time=time(9, 0),
                    end_time=time(10, 30),
                    lesson_type='Практика',
                    room='А-403',
                )
            )
            db.add(
                AcademicEvent(
                    user_id=user.id,
                    subject_id=subject.id,
                    title='Экзамен по ТЕРВЕРУ',
                    event_type='exam',
                    event_date=date(2026, 6, 8),
                    start_time=time(9, 0),
                    room='А-403',
                )
            )
            db.commit()

            context = build_calendar_event_map(user, db, 2026, 6)

        june_8_events = context['event_map'][date(2026, 6, 8)]
        self.assertEqual([event['type'] for event in june_8_events], ['academic'])
        self.assertEqual(june_8_events[0]['badge'], 'Экзамен')

    def test_last_study_day_allows_june_classes_until_cutoff(self):
        with self.SessionLocal() as db:
            user = User(
                username='cutoff-user',
                email='cutoff@example.com',
                password_hash='hash',
                last_study_day=date(2026, 6, 15),
            )
            subject = Subject(user=user, name='История')
            db.add_all([user, subject])
            db.flush()
            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=subject.id,
                    weekday=0,
                    start_time=time(12, 10),
                    end_time=time(13, 40),
                )
            )
            db.commit()

            context = build_calendar_event_map(user, db, 2026, 6)

        self.assertEqual(context['event_map'][date(2026, 6, 15)][0]['type'], 'schedule')
        self.assertEqual(context['event_map'][date(2026, 6, 22)], [])

    def test_day_override_hides_regular_schedule_and_keeps_manual_change(self):
        with self.SessionLocal() as db:
            user = User(username='override-user', email='override@example.com', password_hash='hash')
            subject = Subject(user=user, name='Математика')
            db.add_all([user, subject])
            db.flush()
            db.add(
                ScheduleItem(
                    user_id=user.id,
                    subject_id=subject.id,
                    weekday=0,
                    start_time=time(9, 0),
                    end_time=time(10, 30),
                    lesson_type='Лекция',
                    room='101',
                )
            )
            db.add(
                AcademicEvent(
                    user_id=user.id,
                    title='День не по расписанию',
                    event_type='day_override',
                    event_date=date(2026, 5, 18),
                )
            )
            db.add(
                AcademicEvent(
                    user_id=user.id,
                    subject_id=subject.id,
                    title='Дополнительная математика',
                    event_type='changed_class',
                    event_date=date(2026, 5, 18),
                    start_time=time(12, 10),
                    end_time=time(13, 40),
                    room='204',
                )
            )
            db.commit()

            context = build_calendar_event_map(user, db, 2026, 5)

        may_18_events = context['event_map'][date(2026, 5, 18)]
        self.assertEqual([event['type'] for event in may_18_events], ['override', 'schedule-change'])
        self.assertEqual(may_18_events[1]['badge'], 'Разовая пара')


if __name__ == '__main__':
    unittest.main()
