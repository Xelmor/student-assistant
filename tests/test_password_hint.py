from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.rate_limit import auth_rate_limiter
from app.core.security import hash_password
from app.main import app
from app.models import User
from app.services.password_reset_service import generate_password_reset_token


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


class TestPasswordHint:
    def setup_method(self, method):
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        self.db_path = temp_dir / f'{method.__name__}.db'
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
        auth_rate_limiter.clear()
        self.client = TestClient(app)

    def teardown_method(self):
        auth_rate_limiter.clear()
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def register(self, *, password_hint: str):
        csrf_token = extract_csrf_token(self.client.get('/register').text)
        return self.client.post(
            '/register',
            data={
                'username': 'tester',
                'email': 'tester@example.com',
                'password': 'password123',
                'password_hint': password_hint,
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )

    def test_registration_saves_optional_password_hint(self):
        response = self.register(password_hint='Название первой прочитанной книги')

        assert response.status_code == 302
        with self.SessionLocal() as db:
            user = db.query(User).one()
            assert user.password_hint == 'Название первой прочитанной книги'

    def test_registration_rejects_hint_containing_password(self):
        response = self.register(password_hint='Мой пароль password123')

        assert response.status_code == 200
        assert 'не должна содержать сам пароль' in response.text
        with self.SessionLocal() as db:
            assert db.query(User).count() == 0

    def test_login_page_returns_hint_by_username_or_email(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='Tester',
                    email='tester@example.com',
                    password_hash=hash_password('password123'),
                    password_hint='Любимый учебный предмет',
                )
            )
            db.commit()

        login_page = self.client.get('/login')
        csrf_token = extract_csrf_token(login_page.text)
        by_username = self.client.post(
            '/password-hint',
            data={'username': 'tester', 'csrf_token': csrf_token},
        )
        by_email = self.client.post(
            '/password-hint',
            data={'username': 'TESTER@EXAMPLE.COM', 'csrf_token': csrf_token},
        )

        assert by_username.status_code == 200
        assert by_username.json() == {'message': 'Любимый учебный предмет'}
        assert by_email.status_code == 200
        assert by_email.json() == {'message': 'Любимый учебный предмет'}

    def test_unknown_account_and_missing_hint_use_same_message(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='tester',
                    email='tester@example.com',
                    password_hash=hash_password('password123'),
                    password_hint=None,
                )
            )
            db.commit()

        csrf_token = extract_csrf_token(self.client.get('/login').text)
        missing_hint = self.client.post(
            '/password-hint',
            data={'username': 'tester', 'csrf_token': csrf_token},
        )
        unknown_account = self.client.post(
            '/password-hint',
            data={'username': 'unknown', 'csrf_token': csrf_token},
        )

        assert missing_hint.json() == unknown_account.json()
        assert missing_hint.json() == {
            'message': 'Для этого аккаунта подсказка не сохранена.'
        }

    def test_password_reset_clears_old_hint(self):
        with self.SessionLocal() as db:
            user = User(
                username='tester',
                email='tester@example.com',
                password_hash=hash_password('password123'),
                password_hint='Старая подсказка',
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            token = generate_password_reset_token(user)

        reset_page = self.client.get(f'/reset-password?token={token}')
        csrf_token = extract_csrf_token(reset_page.text)
        response = self.client.post(
            '/reset-password',
            data={
                'token': token,
                'new_password': 'new-password123',
                'confirm_password': 'new-password123',
                'csrf_token': csrf_token,
            },
        )

        assert response.status_code == 200
        with self.SessionLocal() as db:
            user = db.query(User).one()
            assert user.password_hint is None
