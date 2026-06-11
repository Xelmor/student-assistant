from __future__ import annotations

import re
import unittest
from datetime import date
from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import Note, ScheduleItem, Subject, Task, User
from app.web.routes.data import MAX_IMPORT_FILE_BYTES


class FormValidationGuardTests(unittest.TestCase):
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

            note = Note(user_id=user.id, subject_id=subject.id, title='Existing note')
            db.add(note)
            db.flush()

            schedule_item = ScheduleItem(
                user_id=user.id,
                subject_id=subject.id,
                weekday=0,
                start_time=time(9, 0),
                end_time=time(10, 30),
            )
            db.add(schedule_item)
            db.commit()

            self.user_id = user.id
            self.subject_id = subject.id
            self.note_id = note.id
            self.schedule_item_id = schedule_item.id

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
        self.assertEqual(response.status_code, 200)
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
        self.assertEqual(login_response.headers['location'], '/dashboard')

    def test_notes_add_invalid_subject_redirects_with_error(self):
        response = self.client.post(
            '/notes/add',
            data={
                'title': 'Bad note',
                'subject_id': 'abc',
                'content': 'Text',
                'link': '',
                'csrf_token': self._extract_csrf_token(self.client.get('/notes').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/notes?', response.headers['location'])
        self.assertIn('form_error=', response.headers['location'])

        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('Не удалось определить выбранный предмет для заметки.', page.text)

    def test_notes_edit_invalid_subject_keeps_note_open(self):
        response = self.client.post(
            f'/notes/edit/{self.note_id}',
            data={
                'title': 'Existing note',
                'subject_id': 'not-a-number',
                'content': '',
                'link': '',
                'csrf_token': self._extract_csrf_token(self.client.get('/notes').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'note={self.note_id}', response.headers['location'])

        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('Не удалось определить выбранный предмет для заметки.', page.text)
        self.assertIn(f'id="note-edit-{self.note_id}" class="mt-3 pt-3 border-top"', page.text)

    def test_notes_reject_dangerous_link_scheme(self):
        response = self.client.post(
            '/notes/add',
            data={
                'title': 'Unsafe link',
                'subject_id': '',
                'content': '',
                'link': 'javascript:alert(1)',
                'csrf_token': self._extract_csrf_token(self.client.get('/notes').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('form_error=', response.headers['location'])
        with self.SessionLocal() as db:
            self.assertEqual(db.query(Note).filter(Note.title == 'Unsafe link').count(), 0)

    def test_existing_dangerous_note_link_is_not_rendered_as_href(self):
        with self.SessionLocal() as db:
            note = db.query(Note).filter(Note.id == self.note_id).one()
            note.link = 'data:text/html,<script>alert(1)</script>'
            db.commit()

        page = self.client.get('/notes')

        self.assertEqual(page.status_code, 200)
        self.assertNotIn('href="data:', page.text)
        self.assertIn('Ссылка скрыта из-за небезопасного формата.', page.text)

    def test_notes_accept_https_link_with_safe_target_attributes(self):
        response = self.client.post(
            '/notes/add',
            data={
                'title': 'Safe link',
                'subject_id': '',
                'content': '',
                'link': ' https://example.com/docs ',
                'csrf_token': self._extract_csrf_token(self.client.get('/notes').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        page = self.client.get('/notes')
        self.assertIn('href="https://example.com/docs"', page.text)
        self.assertIn('rel="noopener noreferrer"', page.text)

    def test_notes_accept_multiline_content(self):
        content = 'Первая строка\nВторая строка\n\tПункт'
        response = self.client.post(
            '/notes/add',
            data={
                'title': 'Multiline note',
                'subject_id': '',
                'content': content,
                'link': '',
                'csrf_token': self._extract_csrf_token(self.client.get('/notes').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.SessionLocal() as db:
            note = db.query(Note).filter(Note.title == 'Multiline note').one()
            self.assertEqual(note.content, content)

    def test_subject_rejects_css_injection_in_color(self):
        response = self.client.post(
            '/subjects/add',
            data={
                'name': 'Unsafe color',
                'teacher': '',
                'room': '',
                'color': 'red; background-image: url(https://evil.example)',
                'notes': '',
                'csrf_token': self._extract_csrf_token(self.client.get('/subjects').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('form_error=', response.headers['location'])
        with self.SessionLocal() as db:
            self.assertEqual(db.query(Subject).filter(Subject.name == 'Unsafe color').count(), 0)

    def test_existing_invalid_subject_color_is_rendered_with_safe_fallback(self):
        with self.SessionLocal() as db:
            subject = db.query(Subject).filter(Subject.id == self.subject_id).one()
            subject.color = 'red; background-image: url(https://evil.example)'
            db.commit()

        page = self.client.get('/subjects')

        self.assertEqual(page.status_code, 200)
        self.assertNotIn('background-image: url(https://evil.example)', page.text)
        self.assertIn('--subject-color: #3b82f6', page.text)

    def test_task_rejects_unknown_priority(self):
        response = self.client.post(
            '/tasks/add',
            data={
                'title': 'Invalid priority',
                'description': '',
                'subject_id': str(self.subject_id),
                'deadline': '',
                'scheduled_for_date': '',
                'priority': 'critical',
                'difficulty': 'medium',
                'recurrence_type': 'none',
                'recurrence_interval_days': '',
                'schedule_item_id': '',
                'csrf_token': self._extract_csrf_token(self.client.get('/tasks').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('form_error=', response.headers['location'])
        with self.SessionLocal() as db:
            self.assertEqual(db.query(Task).filter(Task.title == 'Invalid priority').count(), 0)

    def test_schedule_rejects_oversized_room(self):
        response = self.client.post(
            '/schedule/add',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '2',
                'start_time': '12:00',
                'end_time': '13:30',
                'lesson_type': 'Lecture',
                'room': 'A' * 51,
                'csrf_token': self._extract_csrf_token(self.client.get('/schedule').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('form_error=', response.headers['location'])
        with self.SessionLocal() as db:
            self.assertEqual(
                db.query(ScheduleItem).filter(ScheduleItem.weekday == 2).count(),
                0,
            )

    def test_schedule_add_invalid_time_redirects_with_error(self):
        response = self.client.post(
            '/schedule/add',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '0',
                'start_time': 'bad-time',
                'end_time': '10:30',
                'lesson_type': 'Lecture',
                'room': '101',
                'csrf_token': self._extract_csrf_token(self.client.get('/schedule').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/schedule?', response.headers['location'])
        self.assertIn('form_error=', response.headers['location'])

        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('Время занятия указано в неверном формате.', page.text)

    def test_schedule_edit_invalid_time_keeps_row_open(self):
        response = self.client.post(
            f'/schedule/edit/{self.schedule_item_id}',
            data={
                'subject_id': str(self.subject_id),
                'weekday': '0',
                'start_time': '11:00',
                'end_time': '10:00',
                'lesson_type': 'Lecture',
                'room': '101',
                'csrf_token': self._extract_csrf_token(self.client.get('/schedule').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'item={self.schedule_item_id}', response.headers['location'])

        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('Время окончания должно быть позже времени начала.', page.text)
        self.assertIn(f'id="schedule-edit-{self.schedule_item_id}" class=""', page.text)


    def test_schedule_delete_clears_task_link_before_removing_item(self):
        with self.SessionLocal() as db:
            task = Task(
                user_id=self.user_id,
                subject_id=self.subject_id,
                schedule_item_id=self.schedule_item_id,
                title='Linked task',
            )
            db.add(task)
            db.commit()
            task_id = task.id

        response = self.client.post(
            f'/schedule/delete/{self.schedule_item_id}',
            data={'csrf_token': self._extract_csrf_token(self.client.get('/schedule').text)},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/schedule')

        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).one()
            self.assertIsNone(task.schedule_item_id)
            self.assertEqual(db.query(ScheduleItem).count(), 0)

    def test_calendar_settings_save_last_study_day(self):
        response = self.client.post(
            '/calendar/settings',
            data={
                'last_study_day': '2026-05-31',
                'year': '2026',
                'month': '5',
                'selected': '2026-05-30',
                'view': 'month',
                'csrf_token': self._extract_csrf_token(self.client.get('/calendar').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['location'],
            '/calendar?year=2026&month=5&selected=2026-05-30&view=month',
        )

        with self.SessionLocal() as db:
            user = db.query(User).filter(User.id == self.user_id).one()
            self.assertEqual(user.last_study_day, date(2026, 5, 31))

    def test_calendar_settings_invalid_date_redirects_with_error(self):
        response = self.client.post(
            '/calendar/settings',
            data={
                'last_study_day': 'bad-date',
                'year': '2026',
                'month': '5',
                'selected': '2026-05-30',
                'view': 'month',
                'csrf_token': self._extract_csrf_token(self.client.get('/calendar').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('calendar_error=', response.headers['location'])

        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('Дата указана в неверном формате.', page.text)

    def test_calendar_settings_trailing_slash_is_accepted(self):
        response = self.client.post(
            '/calendar/settings/',
            data={
                'last_study_day': '2026-06-10',
                'year': '2026',
                'month': '6',
                'selected': '2026-06-10',
                'view': 'month',
                'csrf_token': self._extract_csrf_token(self.client.get('/calendar').text),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['location'],
            '/calendar?year=2026&month=6&selected=2026-06-10&view=month',
        )

    def test_calendar_settings_get_redirects_to_calendar(self):
        response = self.client.get('/calendar/settings', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/calendar')

    def test_data_import_rejects_oversized_file(self):
        response = self.client.post(
            '/data/import',
            data={
                'import_mode': 'merge',
                'csrf_token': self._extract_csrf_token(self.client.get('/profile').text),
            },
            files={
                'import_file': (
                    'backup.json',
                    b' ' * (MAX_IMPORT_FILE_BYTES + 1),
                    'application/json',
                ),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('data_error=', response.headers['location'])


if __name__ == '__main__':
    unittest.main()
