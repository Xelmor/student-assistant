from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import User
from app.services.password_reset_service import (
    generate_password_reset_token,
    load_password_reset_payload,
    validate_password_reset_token,
)
from app.web.routes.auth import PASSWORD_RESET_GENERIC_SUCCESS


class PasswordResetSecurityTests(unittest.TestCase):
    def setUp(self):
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        self.db_path = temp_dir / f'{self._testMethodName}.db'
        self.db_path.unlink(missing_ok=True)
        self.engine = create_engine(
            f'sqlite:///{self.db_path.resolve().as_posix()}',
            connect_args={'check_same_thread': False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

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
                username='reset-user',
                email='reset@example.com',
                password_hash=hash_password('password123'),
            )
            db.add(user)
            db.commit()
            self.user_id = user.id

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        self.db_path.unlink(missing_ok=True)

    @staticmethod
    def _csrf(html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if not match:
            raise AssertionError('CSRF token not found')
        return match.group(1)

    def test_token_payload_does_not_contain_password_hash(self):
        with self.SessionLocal() as db:
            user = db.query(User).filter(User.id == self.user_id).one()
            token = generate_password_reset_token(user)
            payload = load_password_reset_payload(token)

        self.assertNotIn('password_hash', payload)
        self.assertIn('password_version', payload)

    def test_token_becomes_invalid_after_password_change(self):
        with self.SessionLocal() as db:
            user = db.query(User).filter(User.id == self.user_id).one()
            token = generate_password_reset_token(user)
            self.assertTrue(validate_password_reset_token(token, user))
            user.password_hash = hash_password('another-password')
            db.commit()
            self.assertFalse(validate_password_reset_token(token, user))

    def test_forgot_password_returns_generic_success_when_smtp_is_disabled(self):
        page = self.client.get('/forgot-password')
        response = self.client.post(
            '/forgot-password',
            data={
                'email': 'reset@example.com',
                'csrf_token': self._csrf(page.text),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(PASSWORD_RESET_GENERIC_SUCCESS, response.text)
        self.assertNotIn('SMTP', response.text)

    def test_delivery_failure_does_not_change_public_response(self):
        page = self.client.get('/forgot-password')
        with (
            patch('app.web.routes.auth.password_reset_enabled', return_value=True),
            patch('app.web.routes.auth.send_password_reset_email', side_effect=RuntimeError('smtp down')),
        ):
            response = self.client.post(
                '/forgot-password',
                data={
                    'email': 'reset@example.com',
                    'csrf_token': self._csrf(page.text),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(PASSWORD_RESET_GENERIC_SUCCESS, response.text)
        self.assertNotIn('smtp down', response.text)

    def test_forgot_password_rejects_invalid_email(self):
        page = self.client.get('/forgot-password')
        response = self.client.post(
            '/forgot-password',
            data={
                'email': 'not-an-email',
                'csrf_token': self._csrf(page.text),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('корректный email', response.text)


if __name__ == '__main__':
    unittest.main()
