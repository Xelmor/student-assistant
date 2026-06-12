from __future__ import annotations

import re
import unittest
from datetime import date, time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.rate_limit import auth_rate_limiter
from app.core.security import hash_password
from app.main import app
from app.models import AcademicEvent, ScheduleItem, Subject, Task, User


class OnboardingTests(unittest.TestCase):
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
        auth_rate_limiter.clear()
        self.client = TestClient(app)

    def tearDown(self):
        auth_rate_limiter.clear()
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def _extract_csrf_token(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def _register(self, *, group_name: str = '', course: str = ''):
        csrf_token = self._extract_csrf_token(self.client.get('/register').text)
        response = self.client.post(
            '/register',
            data={
                'username': 'new-user',
                'email': 'new-user@example.com',
                'password': 'password123',
                'group_name': group_name,
                'course': course,
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/dashboard')

    def _login(self):
        csrf_token = self._extract_csrf_token(self.client.get('/login').text)
        response = self.client.post(
            '/login',
            data={
                'username': 'new-user',
                'password': 'password123',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def _logout(self):
        csrf_token = self._extract_csrf_token(self.client.get('/profile').text)
        response = self.client.post(
            '/logout',
            data={'csrf_token': csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_new_empty_account_sees_onboarding(self):
        self._register()

        page = self.client.get('/dashboard')

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="dashboardOnboarding"', page.text)
        self.assertIn('id="onboardingChat"', page.text)
        self.assertIn('data-onboarding-completed="0"', page.text)
        self.assertIn('data-onboarding-total="4"', page.text)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            self.assertFalse(user.onboarding_completed)
            self.assertFalse(user.onboarding_chat_completed)

    def test_chat_receives_registration_metadata_and_marks_only_name_missing(self):
        self._register(group_name='ИКБО-42-24', course='2')

        page = self.client.get('/dashboard')

        self.assertIn('data-username="new-user"', page.text)
        self.assertIn('data-display-name=""', page.text)
        self.assertIn('data-group-name="ИКБО-42-24"', page.text)
        self.assertIn('data-course="2"', page.text)
        self.assertIn('спрошу только то, чего не хватает', page.text)

    def test_chat_with_complete_profile_starts_with_interface_setup(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='new-user',
                    email='new-user@example.com',
                    password_hash=hash_password('password123'),
                    display_name='Максим',
                    group_name='ИКБО-42-24',
                    course=2,
                    onboarding_chat_completed=False,
                )
            )
            db.commit()

        self._login()
        page = self.client.get('/dashboard')

        self.assertIn('Привет, Максим! Аккаунт уже создан.', page.text)
        self.assertIn('Осталось настроить внешний вид и формат времени.', page.text)

    def test_chat_completion_saves_profile_and_keeps_action_checklist(self):
        self._register()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)

        response = self.client.post(
            '/onboarding/chat/complete',
            data={
                'display_name': 'Максим',
                'group_name': 'ИКБО-42-24',
                'course': '2',
                'accent': 'blue',
                'time_format': '24',
                'destination': '/dashboard',
                'csrf_token': csrf_token,
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], '/dashboard?onboarding_chat=completed')
        with self.SessionLocal() as db:
            user = db.query(User).one()
            self.assertTrue(user.onboarding_chat_completed)
            self.assertFalse(user.onboarding_completed)
            self.assertEqual(user.display_name, 'Максим')
            self.assertEqual(user.group_name, 'ИКБО-42-24')
            self.assertEqual(user.course, 2)

        page = self.client.get('/dashboard')
        self.assertNotIn('id="onboardingChat"', page.text)
        self.assertIn('id="dashboardOnboarding"', page.text)
        self.assertIn('<strong>Максим</strong>', page.text)

        self._logout()
        self._login()
        self.assertNotIn('id="onboardingChat"', self.client.get('/dashboard').text)

    def test_chat_skip_persists_and_restart_opens_it_again(self):
        self._register(group_name='ИКБО-42-24', course='2')
        with self.SessionLocal() as db:
            user = db.query(User).one()
            user.display_name = 'Максим'
            db.commit()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)

        response = self.client.post(
            '/onboarding/chat/skip',
            data={'csrf_token': csrf_token},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], '/dashboard?onboarding_chat=skipped')
        self.assertNotIn('id="onboardingChat"', self.client.get('/dashboard').text)

        profile_page = self.client.get('/profile')
        restart_csrf = self._extract_csrf_token(profile_page.text)
        restart = self.client.post(
            '/onboarding/chat/restart',
            data={'csrf_token': restart_csrf},
            follow_redirects=False,
        )

        self.assertEqual(restart.status_code, 302)
        self.assertEqual(restart.headers['location'], '/dashboard?onboarding_chat=restart')
        restarted_page = self.client.get(restart.headers['location'])
        self.assertIn('id="onboardingChat"', restarted_page.text)
        self.assertIn('data-restart="true"', restarted_page.text)
        self.assertIn('value="Максим"', restarted_page.text)
        self.assertIn('value="ИКБО-42-24"', restarted_page.text)
        self.assertIn('value="2"', restarted_page.text)

    def test_chat_does_not_erase_existing_profile_with_empty_values(self):
        self._register(group_name='ИКБО-42-24', course='2')
        with self.SessionLocal() as db:
            user = db.query(User).one()
            user.display_name = 'Максим'
            db.commit()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)

        response = self.client.post(
            '/onboarding/chat/complete',
            data={
                'display_name': '',
                'group_name': '',
                'course': '',
                'accent': 'purple',
                'time_format': '24',
                'destination': '/dashboard',
                'csrf_token': csrf_token,
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        self.assertEqual(response.status_code, 200)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            self.assertEqual(user.display_name, 'Максим')
            self.assertEqual(user.group_name, 'ИКБО-42-24')
            self.assertEqual(user.course, 2)

    def test_chat_rejects_invalid_profile_values(self):
        self._register()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)

        response = self.client.post(
            '/onboarding/chat/complete',
            data={
                'display_name': '   ',
                'group_name': '',
                'course': '',
                'accent': 'invalid',
                'time_format': '24',
                'destination': '/dashboard',
                'csrf_token': csrf_token,
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        self.assertEqual(response.status_code, 422)
        with self.SessionLocal() as db:
            self.assertFalse(db.query(User).one().onboarding_chat_completed)

    def test_skip_persists_after_logout_and_login(self):
        self._register()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)

        response = self.client.post(
            '/onboarding/skip',
            data={'csrf_token': csrf_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/dashboard?onboarding=skipped')
        self.assertNotIn('id="dashboardOnboarding"', self.client.get('/dashboard').text)

        self._logout()
        self._login()
        self.assertNotIn('id="dashboardOnboarding"', self.client.get('/dashboard').text)

    def test_complete_requires_all_steps_and_then_hides_onboarding(self):
        self._register()
        csrf_token = self._extract_csrf_token(self.client.get('/dashboard').text)
        early_response = self.client.post(
            '/onboarding/complete',
            data={'csrf_token': csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(early_response.headers['location'], '/dashboard?onboarding=incomplete')

        with self.SessionLocal() as db:
            user = db.query(User).one()
            subject = Subject(user_id=user.id, name='First subject')
            db.add(subject)
            db.flush()
            db.add_all(
                [
                    Task(user_id=user.id, subject_id=subject.id, title='First task'),
                    ScheduleItem(
                        user_id=user.id,
                        subject_id=subject.id,
                        weekday=0,
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                    ),
                    AcademicEvent(
                        user_id=user.id,
                        subject_id=subject.id,
                        title='First event',
                        event_type='exam',
                        event_date=date(2026, 6, 20),
                    ),
                ]
            )
            db.commit()

        ready_page = self.client.get('/dashboard')
        self.assertIn('Рабочее пространство готово!', ready_page.text)
        self.assertIn('data-onboarding-completed="4"', ready_page.text)
        csrf_token = self._extract_csrf_token(ready_page.text)
        response = self.client.post(
            '/onboarding/complete',
            data={'csrf_token': csrf_token},
            follow_redirects=False,
        )

        self.assertEqual(response.headers['location'], '/dashboard?onboarding=completed')
        self.assertNotIn('id="dashboardOnboarding"', self.client.get('/dashboard').text)

    def test_calendar_open_marks_step_without_completing_onboarding(self):
        self._register()

        response = self.client.get('/calendar?onboarding_step=calendar')

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="onboardingCalendarCompleted"', response.text)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            self.assertTrue(user.onboarding_calendar_opened)
            self.assertFalse(user.onboarding_completed)

        dashboard = self.client.get('/dashboard')
        self.assertIn('data-onboarding-completed="1"', dashboard.text)

    def test_completed_account_never_renders_onboarding(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username='new-user',
                    email='new-user@example.com',
                    password_hash=hash_password('password123'),
                    onboarding_completed=True,
                )
            )
            db.commit()

        self._login()

        self.assertNotIn('id="dashboardOnboarding"', self.client.get('/dashboard').text)


if __name__ == '__main__':
    unittest.main()
