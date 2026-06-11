from __future__ import annotations

import re
import unittest
from datetime import date, time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import AcademicEvent, Note, ScheduleItem, Subject, Task, User


class SecurityAccessTests(unittest.TestCase):
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

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            current_user = User(
                username='current-user',
                email='current@example.com',
                password_hash=hash_password('password123'),
            )
            other_user = User(
                username='other-user',
                email='other@example.com',
                password_hash=hash_password('password123'),
            )
            db.add_all([current_user, other_user])
            db.flush()

            other_subject = Subject(
                user_id=other_user.id,
                name='Private subject marker',
            )
            db.add(other_subject)
            db.flush()

            other_task = Task(
                user_id=other_user.id,
                subject_id=other_subject.id,
                title='Private task marker',
            )
            other_note = Note(
                user_id=other_user.id,
                subject_id=other_subject.id,
                title='Private note marker',
            )
            other_schedule = ScheduleItem(
                user_id=other_user.id,
                subject_id=other_subject.id,
                weekday=1,
                start_time=time(9, 0),
                end_time=time(10, 30),
            )
            other_event = AcademicEvent(
                user_id=other_user.id,
                subject_id=other_subject.id,
                title='Private event marker',
                event_type='exam',
                event_date=date(2026, 6, 15),
            )
            db.add_all([other_task, other_note, other_schedule, other_event])
            db.commit()

            self.other_subject_id = other_subject.id
            self.other_task_id = other_task.id
            self.other_note_id = other_note.id
            self.other_schedule_id = other_schedule.id
            self.other_event_id = other_event.id

        self._login()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def _extract_csrf_token(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self):
        csrf_token = self._extract_csrf_token(self.client.get('/login').text)
        response = self.client.post(
            '/login',
            data={
                'username': 'current-user',
                'password': 'password123',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_private_pages_do_not_render_other_users_objects(self):
        for path, marker in [
            ('/subjects', 'Private subject marker'),
            ('/tasks', 'Private task marker'),
            ('/notes', 'Private note marker'),
            ('/calendar?selected=2026-06-15', 'Private event marker'),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(marker, response.text)

    def test_delete_routes_cannot_remove_other_users_objects(self):
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)
        for path in [
            f'/tasks/delete/{self.other_task_id}',
            f'/notes/delete/{self.other_note_id}',
            f'/schedule/delete/{self.other_schedule_id}',
            f'/calendar/session/delete/{self.other_event_id}',
            f'/subjects/delete/{self.other_subject_id}',
        ]:
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    data={'csrf_token': csrf_token},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 302)

        with self.SessionLocal() as db:
            self.assertIsNotNone(db.get(Task, self.other_task_id))
            self.assertIsNotNone(db.get(Note, self.other_note_id))
            self.assertIsNotNone(db.get(ScheduleItem, self.other_schedule_id))
            self.assertIsNotNone(db.get(AcademicEvent, self.other_event_id))
            self.assertIsNotNone(db.get(Subject, self.other_subject_id))

    def test_mutation_without_csrf_is_rejected(self):
        response = self.client.post(
            '/subjects/add',
            data={
                'name': 'Missing CSRF',
                'teacher': '',
                'room': '',
                'color': '#8b5cf6',
                'notes': '',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 403)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(Subject).filter(Subject.name == 'Missing CSRF').count(), 0)


if __name__ == '__main__':
    unittest.main()
