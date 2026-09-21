from __future__ import annotations

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import User


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
