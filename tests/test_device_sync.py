from __future__ import annotations

import re
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.rate_limit import auth_rate_limiter
from app.core.time import current_time
from app.main import app
from app.models import DeviceLinkSession, Task, User, Workspace, WorkspaceDevice
from app.services.workspace_sync import hash_recovery_key


class DeviceSyncTests(unittest.TestCase):
    def setUp(self):
        auth_rate_limiter.clear()
        temp_dir = Path('tests/.tmp')
        temp_dir.mkdir(exist_ok=True)
        self.db_path = temp_dir / f'device_sync_{self._testMethodName}.db'
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
        self.clients: list[TestClient] = []
        self.owner = self._client()

    def tearDown(self):
        app.dependency_overrides.clear()
        for client in self.clients:
            client.close()
        self.engine.dispose()
        auth_rate_limiter.clear()
        if self.db_path.exists():
            self.db_path.unlink()

    def _client(self) -> TestClient:
        client = TestClient(app)
        self.clients.append(client)
        return client

    @staticmethod
    def _csrf(html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if not match:
            raise AssertionError('CSRF token not found')
        return match.group(1)

    def _create_workspace(self, *, show_recovery: bool = False) -> tuple[object, str | None]:
        landing = self.owner.get('/')
        response = self.owner.post(
            '/start',
            data={
                'display_name': 'Максим',
                'group_name': 'ИКБО-42-24',
                'course': '2',
                'schedule_unit': 'pair',
                'show_recovery': '1' if show_recovery else '0',
                'csrf_token': self._csrf(landing.text),
            },
            follow_redirects=False,
        )
        recovery_key = None
        if show_recovery:
            match = re.search(r'data-recovery-key>([^<]+)</output>', response.text)
            if not match:
                raise AssertionError('Recovery key not found')
            recovery_key = match.group(1).strip()
        return response, recovery_key

    def _issue_link(self) -> dict:
        profile = self.owner.get('/profile')
        response = self.owner.post(
            '/profile/devices/link-session',
            data={'csrf_token': self._csrf(profile.text)},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/json', response.headers['content-type'])
        payload = response.json()
        self.assertRegex(payload['code'], r'^\d{6}$')
        self.assertTrue(payload['qr_data_uri'].startswith('data:image/svg+xml;base64,'))
        return payload

    def _issue_code(self) -> str:
        return self._issue_link()['code']

    def _connect_with_code(self, client: TestClient, code: str):
        page = client.get('/connect-device')
        return client.post(
            '/connect-device/code',
            data={
                'code': code,
                'device_name': 'Телефон',
                'csrf_token': self._csrf(page.text),
            },
            follow_redirects=False,
        )

    def _recover(self, client: TestClient, key: str):
        page = client.get('/recover')
        return client.post(
            '/recover',
            data={
                'recovery_key': key,
                'device_name': 'Резервный телефон',
                'csrf_token': self._csrf(page.text),
            },
            follow_redirects=False,
        )

    def test_first_start_creates_workspace_and_first_device(self):
        response, recovery_key = self._create_workspace(show_recovery=True)
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(recovery_key)
        with self.SessionLocal() as db:
            workspace = db.query(Workspace).one()
            device = db.query(WorkspaceDevice).one()
            self.assertEqual(workspace.user_id, db.query(User).one().id)
            self.assertEqual(device.workspace_id, workspace.id)
            self.assertEqual(workspace.recovery_key_hash, hash_recovery_key(recovery_key or ''))
            self.assertNotEqual(workspace.recovery_key_hash, recovery_key)

    def test_generates_hashed_six_digit_pairing_code(self):
        self._create_workspace()
        code = self._issue_code()
        with self.SessionLocal() as db:
            link = db.query(DeviceLinkSession).one()
            self.assertNotEqual(link.code_hash, code)
            self.assertEqual((link.expires_at - link.created_at).total_seconds(), 300)

    def test_link_session_returns_json_and_existing_qr_route(self):
        self._create_workspace()
        payload = self._issue_link()
        self.assertEqual(payload['expires_in_seconds'], 300)
        self.assertIn('expires_at', payload)
        self.assertIn('link_url', payload)

        qr_url = urlsplit(payload['link_url'])
        self.assertEqual(qr_url.path, '/link-device')
        response = self.owner.get(f'{qr_url.path}?{qr_url.query}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Подключить это устройство', response.text)

    def test_link_frontend_uses_server_generated_registered_endpoint(self):
        self._create_workspace()
        profile = self.owner.get('/profile')
        endpoint_match = re.search(r'data-link-session-url="([^"]+)"', profile.text)
        self.assertIsNotNone(endpoint_match)
        endpoint = urlsplit(endpoint_match.group(1)).path
        self.assertEqual(endpoint, '/profile/devices/link-session')
        self.assertIn(endpoint, app.openapi()['paths'])

        source = Path('app/static/js/device-sync.js').read_text(encoding='utf-8')
        self.assertIn('openButton.dataset.linkSessionUrl', source)
        self.assertNotIn("fetch('/profile/devices/link-session'", source)
        self.assertIn("includes('application/json')", source)

    def test_unknown_json_api_request_does_not_return_html(self):
        response = self.owner.post(
            '/profile/devices/unknown-endpoint',
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('application/json', response.headers['content-type'])
        self.assertIn('error', response.json())

    def test_expired_pairing_code_is_rejected(self):
        self._create_workspace()
        code = self._issue_code()
        with self.SessionLocal() as db:
            link = db.query(DeviceLinkSession).one()
            link.expires_at = current_time() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self._connect_with_code(self._client(), code).status_code, 400)

    def test_pairing_code_is_one_time(self):
        self._create_workspace()
        code = self._issue_code()
        self.assertEqual(self._connect_with_code(self._client(), code).status_code, 302)
        self.assertEqual(self._connect_with_code(self._client(), code).status_code, 400)

    def test_wrong_pairing_code_is_rejected(self):
        self._create_workspace()
        self._issue_code()
        self.assertEqual(self._connect_with_code(self._client(), '000 001').status_code, 400)

    def test_pairing_attempts_are_rate_limited(self):
        self._create_workspace()
        client = self._client()
        statuses = [self._connect_with_code(client, '111111').status_code for _ in range(7)]
        self.assertEqual(statuses[:6], [400] * 6)
        self.assertEqual(statuses[6], 429)

    def test_second_device_is_created(self):
        self._create_workspace()
        response = self._connect_with_code(self._client(), self._issue_code())
        self.assertEqual(response.status_code, 302)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(WorkspaceDevice).filter(WorkspaceDevice.revoked_at.is_(None)).count(), 2)

    def test_both_devices_see_the_same_tasks(self):
        self._create_workspace()
        phone = self._client()
        self.assertEqual(self._connect_with_code(phone, self._issue_code()).status_code, 302)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            db.add(Task(user_id=user.id, title='Синхронная задача'))
            db.commit()
        for client in (self.owner, phone):
            response = client.get('/tasks')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Синхронная задача', response.text)

    def test_owner_can_revoke_another_device(self):
        self._create_workspace()
        phone = self._client()
        self._connect_with_code(phone, self._issue_code())
        with self.SessionLocal() as db:
            device = db.query(WorkspaceDevice).order_by(WorkspaceDevice.id.desc()).first()
            phone_device_id = device.id
        profile = self.owner.get('/profile')
        response = self.owner.post(
            f'/profile/devices/{phone_device_id}/revoke',
            data={'csrf_token': self._csrf(profile.text)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.SessionLocal() as db:
            self.assertIsNotNone(db.get(WorkspaceDevice, phone_device_id).revoked_at)

    def test_revoked_device_loses_access_on_next_request(self):
        self._create_workspace()
        phone = self._client()
        self._connect_with_code(phone, self._issue_code())
        with self.SessionLocal() as db:
            device = db.query(WorkspaceDevice).order_by(WorkspaceDevice.id.desc()).first()
            phone_device_id = device.id
        profile = self.owner.get('/profile')
        self.owner.post(
            f'/profile/devices/{phone_device_id}/revoke',
            data={'csrf_token': self._csrf(profile.text)},
        )
        response = phone.get('/dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/')

    def test_current_device_requires_explicit_confirmation_to_revoke(self):
        self._create_workspace()
        with self.SessionLocal() as db:
            device_id = db.query(WorkspaceDevice).one().id
        profile = self.owner.get('/profile')
        csrf = self._csrf(profile.text)
        rejected = self.owner.post(
            f'/profile/devices/{device_id}/revoke',
            data={'csrf_token': csrf},
            follow_redirects=False,
        )
        self.assertIn('device_error=confirm-current', rejected.headers['location'])
        with self.SessionLocal() as db:
            self.assertIsNone(db.get(WorkspaceDevice, device_id).revoked_at)

        profile = self.owner.get('/profile')
        confirmed = self.owner.post(
            f'/profile/devices/{device_id}/revoke',
            data={
                'csrf_token': self._csrf(profile.text),
                'confirm_current': 'ОТКЛЮЧИТЬ',
            },
            follow_redirects=False,
        )
        self.assertEqual(confirmed.headers['location'], '/?device_revoked=1')
        with self.SessionLocal() as db:
            self.assertIsNotNone(db.get(WorkspaceDevice, device_id).revoked_at)

    def test_valid_recovery_key_restores_workspace(self):
        _, key = self._create_workspace(show_recovery=True)
        response = self._recover(self._client(), key or '')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/dashboard?recovered=1')
        with self.SessionLocal() as db:
            self.assertEqual(db.query(WorkspaceDevice).count(), 2)

    def test_wrong_recovery_key_is_rejected(self):
        self._create_workspace(show_recovery=True)
        response = self._recover(self._client(), 'SA-AAAA-AAAA-AAAA-AAAA-AAAA')
        self.assertEqual(response.status_code, 400)

    def test_rotated_recovery_key_invalidates_old_key(self):
        _, old_key = self._create_workspace(show_recovery=True)
        profile = self.owner.get('/profile')
        response = self.owner.post(
            '/profile/recovery-key/rotate',
            data={'csrf_token': self._csrf(profile.text)},
        )
        match = re.search(r'data-recovery-key>([^<]+)</output>', response.text)
        self.assertIsNotNone(match)
        new_key = match.group(1).strip()
        self.assertEqual(self._recover(self._client(), old_key or '').status_code, 400)
        self.assertEqual(self._recover(self._client(), new_key).status_code, 302)

    def test_logout_preserves_workspace_and_devices(self):
        self._create_workspace()
        profile = self.owner.get('/profile')
        response = self.owner.post(
            '/logout',
            data={'csrf_token': self._csrf(profile.text)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(Workspace).count(), 1)
            self.assertEqual(db.query(WorkspaceDevice).count(), 1)
            self.assertIsNone(db.query(WorkspaceDevice).one().revoked_at)


if __name__ == '__main__':
    unittest.main()
