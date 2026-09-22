from __future__ import annotations

import re
import unittest
from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Note, ScheduleItem, Subject, Task, User


class LocalStartTests(unittest.TestCase):
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

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    @staticmethod
    def _csrf(html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if not match:
            raise AssertionError('CSRF token not found')
        return match.group(1)

    def _create_local_profile(self):
        landing = self.client.get('/')
        return self.client.post(
            '/start',
            data={
                'display_name': 'Максим',
                'group_name': 'ИКБО-42-24',
                'course': '2',
                'schedule_unit': 'pair',
                'csrf_token': self._csrf(landing.text),
            },
            follow_redirects=False,
        )

    def test_start_creates_passwordless_device_profile(self):
        response = self._create_local_profile()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/dashboard?welcome=1')
        self.assertIn('sa_device_profile=', response.headers.get('set-cookie', ''))

        with self.SessionLocal() as db:
            user = db.query(User).one()
            self.assertTrue(user.is_local_profile)
            self.assertEqual(user.display_name, 'Максим')
            self.assertEqual(user.group_name, 'ИКБО-42-24')
            self.assertEqual(user.course, 2)
            self.assertEqual(user.schedule_unit, 'pair')
            self.assertTrue(user.local_access_token_hash)
            self.assertTrue(user.email.endswith('@student-assistant.invalid'))

    def test_device_cookie_restores_session(self):
        self._create_local_profile()
        self.client.cookies.delete('session')

        response = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Максим', response.text)

    def test_logout_clears_device_autologin_without_deleting_data(self):
        self._create_local_profile()
        with self.SessionLocal() as db:
            user = db.query(User).one()
            subject = Subject(user_id=user.id, name='Математика')
            db.add(subject)
            db.flush()
            db.add_all([
                Task(user_id=user.id, subject_id=subject.id, title='Подготовиться'),
                Note(user_id=user.id, subject_id=subject.id, title='Конспект', content='Материал'),
                ScheduleItem(user_id=user.id, subject_id=subject.id, weekday=0,
                             start_time=time(9), end_time=time(10, 30)),
            ])
            db.commit()

        def snapshot():
            with self.engine.connect() as connection:
                return {
                    table.name: connection.execute(table.select()).mappings().all()
                    for table in Base.metadata.sorted_tables
                }

        profile = self.client.get('/profile')
        before = snapshot()
        response = self.client.post('/logout', data={'csrf_token': self._csrf(profile.text)},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/')
        self.assertNotIn('sa_device_profile', self.client.cookies)
        self.assertNotIn('session', self.client.cookies)
        self.assertEqual(snapshot(), before)

        for _ in range(2):
            landing = self.client.get('/', follow_redirects=False)
            self.assertEqual(landing.status_code, 200)
            self.assertIn('entry-v3-page', landing.text)
        self.assertEqual(self.client.get('/dashboard', follow_redirects=False).status_code, 302)

    def test_logout_requires_csrf_and_preserves_login_on_rejection(self):
        self._create_local_profile()
        response = self.client.post('/logout', follow_redirects=False)
        self.assertEqual(response.status_code, 403)
        self.assertIn('sa_device_profile', self.client.cookies)
        self.assertEqual(self.client.get('/', follow_redirects=False).headers['location'], '/dashboard')

    def test_start_rejects_blank_name(self):
        landing = self.client.get('/')
        response = self.client.post(
            '/start',
            data={
                'display_name': '   ',
                'group_name': '',
                'course': '',
                'schedule_unit': 'pair',
                'csrf_token': self._csrf(landing.text),
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Как тебя называть?', response.text)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(User).count(), 0)
