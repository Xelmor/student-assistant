from __future__ import annotations

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import User


class AccountNormalizationTests(unittest.TestCase):
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

    def _extract_csrf_token(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def _register(self, *, username: str, email: str, password: str = 'password123'):
        response = self.client.get('/register')
        csrf_token = self._extract_csrf_token(response.text)
        return self.client.post(
            '/register',
            data={
                'username': username,
                'email': email,
                'password': password,
                'group_name': '',
                'course': '',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

    def _login(self, username: str = 'tester', password: str = 'password123'):
        response = self.client.get('/login')
        csrf_token = self._extract_csrf_token(response.text)
        return self.client.post(
            '/login',
            data={
                'username': username,
                'password': password,
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

    def test_register_normalizes_username_and_email_before_save(self):
        response = self._register(username='  tester  ', email='  TeSter@Example.COM  ')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/dashboard')

        with self.SessionLocal() as db:
            user = db.query(User).one()

        self.assertEqual(user.username, 'tester')
        self.assertEqual(user.email, 'tester@example.com')

    def test_register_rejects_blank_identity_after_normalization(self):
        response = self._register(username='   ', email='   ', password='password123')

        self.assertEqual(response.status_code, 200)
        self.assertIn('alert alert-danger', response.text)

        with self.SessionLocal() as db:
            self.assertEqual(db.query(User).count(), 0)

    def test_register_rejects_short_password(self):
        response = self._register(username='tester', email='tester@example.com', password='123')

        self.assertEqual(response.status_code, 200)
        self.assertIn('alert alert-danger', response.text)
        self.assertIn('8', response.text)

        with self.SessionLocal() as db:
            self.assertEqual(db.query(User).count(), 0)

    def test_register_rejects_invalid_email(self):
        response = self._register(username='tester', email='not-an-email')

        self.assertEqual(response.status_code, 200)
        self.assertIn('корректный email', response.text)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(User).count(), 0)

    def test_register_rejects_oversized_username(self):
        response = self._register(username='x' * 51, email='tester@example.com')

        self.assertEqual(response.status_code, 200)
        self.assertIn('50', response.text)

    def test_register_rejects_case_insensitive_duplicate_username(self):
        first_response = self._register(username='Tester', email='tester@example.com')
        self.assertEqual(first_response.status_code, 302)

        second_response = self._register(username='tester', email='other@example.com')
        self.assertEqual(second_response.status_code, 200)
        self.assertIn('alert alert-danger', second_response.text)

    def test_login_accepts_case_insensitive_username(self):
        register_response = self._register(username='Tester', email='tester@example.com')
        self.assertEqual(register_response.status_code, 302)
        self.client.post(
            '/logout',
            data={'csrf_token': self._extract_csrf_token(self.client.get('/profile').text)},
            follow_redirects=False,
        )

        login_page = self.client.get('/login')
        csrf_before_login = self._extract_csrf_token(login_page.text)
        login_response = self._login(username='tester')

        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers['location'], '/dashboard')
        csrf_after_login = self._extract_csrf_token(self.client.get('/profile').text)
        self.assertNotEqual(csrf_before_login, csrf_after_login)

    def test_profile_update_normalizes_username_and_email(self):
        self._register(username='tester', email='tester@example.com')
        login_response = self._login()
        self.assertEqual(login_response.status_code, 302)

        profile_page = self.client.get('/profile')
        csrf_token = self._extract_csrf_token(profile_page.text)
        response = self.client.post(
            '/profile',
            data={
                'username': '  updated-user  ',
                'email': '  Updated@Example.COM  ',
                'group_name': '',
                'course': '',
                'schedule_unit': 'class',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)

        with self.SessionLocal() as db:
            user = db.query(User).one()

        self.assertEqual(user.username, 'updated-user')
        self.assertEqual(user.email, 'updated@example.com')

    def test_profile_update_detects_duplicate_normalized_email(self):
        self._register(username='tester', email='tester@example.com')
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='another',
                    email='another@example.com',
                    password_hash=hash_password('password123'),
                )
            )
            db.commit()

        login_response = self._login(username='tester')
        self.assertEqual(login_response.status_code, 302)

        profile_page = self.client.get('/profile')
        csrf_token = self._extract_csrf_token(profile_page.text)
        response = self.client.post(
            '/profile',
            data={
                'username': 'tester',
                'email': '  ANOTHER@EXAMPLE.COM  ',
                'group_name': '',
                'course': '',
                'schedule_unit': 'class',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('alert alert-danger', response.text)

        with self.SessionLocal() as db:
            user = db.query(User).filter(User.username == 'tester').one()

        self.assertEqual(user.email, 'tester@example.com')

    def test_profile_update_detects_case_insensitive_duplicate_username(self):
        self._register(username='Tester', email='tester@example.com')
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='another',
                    email='another@example.com',
                    password_hash=hash_password('password123'),
                )
            )
            db.commit()

        login_response = self._login(username='another')
        self.assertEqual(login_response.status_code, 302)

        profile_page = self.client.get('/profile')
        csrf_token = self._extract_csrf_token(profile_page.text)
        response = self.client.post(
            '/profile',
            data={
                'username': 'tester',
                'email': 'another@example.com',
                'group_name': '',
                'course': '',
                'schedule_unit': 'class',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('alert alert-danger', response.text)

    def test_profile_rejects_invalid_course(self):
        self._register(username='tester', email='tester@example.com')

        profile_page = self.client.get('/profile')
        response = self.client.post(
            '/profile',
            data={
                'username': 'tester',
                'email': 'tester@example.com',
                'group_name': '',
                'course': '99',
                'schedule_unit': 'class',
                'csrf_token': self._extract_csrf_token(profile_page.text),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('от 1 до 12', response.text)


if __name__ == '__main__':
    unittest.main()
