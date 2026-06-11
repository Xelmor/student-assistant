from __future__ import annotations

import re
import unittest
from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import ScheduleItem, Subject, User


class ScheduleConflictTests(unittest.TestCase):
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
            user = User(
                username='tester',
                email='tester@example.com',
                password_hash=hash_password('password123'),
            )
            db.add(user)
            db.flush()

            subject = Subject(user_id=user.id, name='Math')
            db.add(subject)
            db.flush()

            self.user_id = user.id
            self.subject_id = subject.id

            db.commit()

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
        response = self.client.get('/login')
        csrf_token = self._extract_csrf_token(response.text)
        login_response = self.client.post(
            '/login',
            data={
                'username': 'tester',
                'password': 'password123',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def _schedule_csrf(self) -> str:
        return self._extract_csrf_token(self.client.get('/schedule').text)

    def test_schedule_add_reports_incomplete_row_instead_of_skipping(self):
        response = self.client.post(
            '/schedule/add',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '0',
                'start_time': '09:00',
                'end_time': '',
                'lesson_type': '',
                'room': '',
                'csrf_token': self._schedule_csrf(),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.headers['location'])
        self.assertIn('Строка 1: заполнены не все обязательные поля', page.text)

        with self.SessionLocal() as db:
            self.assertEqual(db.query(ScheduleItem).count(), 0)

    def test_schedule_add_rejects_overlap_with_existing_item(self):
        with self.SessionLocal() as db:
            db.add(
                ScheduleItem(
                    user_id=self.user_id,
                    subject_id=self.subject_id,
                    weekday=0,
                    start_time=time(9, 0),
                    end_time=time(10, 30),
                )
            )
            db.commit()

        response = self.client.post(
            '/schedule/add',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '0',
                'start_time': '10:00',
                'end_time': '11:00',
                'lesson_type': '',
                'room': '',
                'csrf_token': self._schedule_csrf(),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.headers['location'])
        self.assertIn('Строка 1: занятие пересекается с уже существующей парой', page.text)

        with self.SessionLocal() as db:
            self.assertEqual(db.query(ScheduleItem).count(), 1)

    def test_schedule_add_rejects_overlap_inside_same_request(self):
        response = self.client.post(
            '/schedule/add',
            data={
                'subject_id': [str(self.subject_id), str(self.subject_id)],
                'weekday': ['0', '0'],
                'start_time': ['09:00', '09:30'],
                'end_time': ['10:00', '10:30'],
                'lesson_type': ['', ''],
                'room': ['', ''],
                'csrf_token': self._schedule_csrf(),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.headers['location'])
        self.assertIn('Строка 2: занятие пересекается с другой строкой формы', page.text)

        with self.SessionLocal() as db:
            self.assertEqual(db.query(ScheduleItem).count(), 0)

    def test_schedule_edit_rejects_overlap_and_keeps_editor_open(self):
        with self.SessionLocal() as db:
            first_item = ScheduleItem(
                user_id=self.user_id,
                subject_id=self.subject_id,
                weekday=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
            second_item = ScheduleItem(
                user_id=self.user_id,
                subject_id=self.subject_id,
                weekday=0,
                start_time=time(10, 30),
                end_time=time(11, 30),
            )
            db.add_all([first_item, second_item])
            db.commit()
            second_item_id = second_item.id

        response = self.client.post(
            f'/schedule/edit/{second_item_id}',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '0',
                'start_time': '09:30',
                'end_time': '10:45',
                'lesson_type': '',
                'room': '',
                'csrf_token': self._schedule_csrf(),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'item={second_item_id}', response.headers['location'])
        page = self.client.get(response.headers['location'])
        self.assertIn('Строка 1: занятие пересекается с уже существующей парой', page.text)
        self.assertIn(f'id="schedule-edit-{second_item_id}" class=""', page.text)


if __name__ == '__main__':
    unittest.main()
