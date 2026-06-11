from __future__ import annotations

import unittest
import zipfile
from io import TextIOWrapper
from datetime import time
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Note, ScheduleItem, Subject, Task, User
from app.services.data_service import build_csv_export_archive, import_user_export_payload
from app.services.data_service import MAX_IMPORT_RECORDS_PER_COLLECTION


class DataImportReplaceTests(unittest.TestCase):
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

        @event.listens_for(self.engine, 'connect')
        def _enable_foreign_keys(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_replace_import_deletes_tasks_before_schedule_items(self):
        with self.SessionLocal() as db:
            user = User(
                username='tester',
                email='tester@example.com',
                password_hash='hash',
            )
            db.add(user)
            db.flush()

            subject = Subject(user_id=user.id, name='Old subject')
            db.add(subject)
            db.flush()

            schedule_item = ScheduleItem(
                user_id=user.id,
                subject_id=subject.id,
                weekday=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
            db.add(schedule_item)
            db.flush()

            db.add(
                Task(
                    user_id=user.id,
                    subject_id=subject.id,
                    schedule_item_id=schedule_item.id,
                    title='Old task',
                )
            )
            db.commit()
            user_id = user.id
            db.expunge_all()
            user = db.query(User).filter(User.id == user_id).one()

            payload = {
                'user': {'schedule_unit': 'class'},
                'data': {
                    'subjects': [{'id': 1, 'name': 'New subject'}],
                    'tasks': [],
                    'schedule_items': [],
                    'notes': [],
                },
            }

            import_user_export_payload(user, payload, 'replace', db)
            db.commit()

            self.assertEqual(db.query(Subject).filter(Subject.user_id == user.id).count(), 1)
            self.assertEqual(db.query(Task).filter(Task.user_id == user.id).count(), 0)
            self.assertEqual(db.query(ScheduleItem).filter(ScheduleItem.user_id == user.id).count(), 0)

    def test_import_rejects_dangerous_note_link(self):
        with self.SessionLocal() as db:
            user = User(username='tester', email='tester@example.com', password_hash='hash')
            db.add(user)
            db.commit()

            payload = {
                'data': {
                    'subjects': [],
                    'tasks': [],
                    'schedule_items': [],
                    'academic_events': [],
                    'notes': [
                        {
                            'title': 'Unsafe',
                            'link': 'javascript:alert(1)',
                        }
                    ],
                },
            }

            with self.assertRaisesRegex(ValueError, 'небезопасную ссылку'):
                import_user_export_payload(user, payload, 'merge', db)

            self.assertEqual(db.query(Note).filter(Note.user_id == user.id).count(), 0)

    def test_import_rejects_too_many_records(self):
        with self.SessionLocal() as db:
            user = User(username='tester', email='tester@example.com', password_hash='hash')
            db.add(user)
            db.commit()
            payload = {
                'data': {
                    'subjects': [
                        {'name': f'Subject {index}'}
                        for index in range(MAX_IMPORT_RECORDS_PER_COLLECTION + 1)
                    ],
                    'tasks': [],
                    'schedule_items': [],
                    'academic_events': [],
                    'notes': [],
                },
            }

            with self.assertRaisesRegex(ValueError, 'слишком|больше'):
                import_user_export_payload(user, payload, 'merge', db)

    def test_import_rejects_css_injection_in_subject_color(self):
        with self.SessionLocal() as db:
            user = User(username='tester', email='tester@example.com', password_hash='hash')
            db.add(user)
            db.commit()
            payload = {
                'data': {
                    'subjects': [
                        {
                            'name': 'Unsafe subject',
                            'color': 'red; background: url(https://evil.example)',
                        }
                    ],
                    'tasks': [],
                    'schedule_items': [],
                    'academic_events': [],
                    'notes': [],
                },
            }

            with self.assertRaisesRegex(ValueError, '#RRGGBB'):
                import_user_export_payload(user, payload, 'merge', db)

            self.assertEqual(
                db.query(Subject).filter(Subject.user_id == user.id).count(),
                0,
            )

    def test_import_rejects_unknown_task_level(self):
        with self.SessionLocal() as db:
            user = User(username='tester', email='tester@example.com', password_hash='hash')
            db.add(user)
            db.commit()
            payload = {
                'data': {
                    'subjects': [],
                    'tasks': [
                        {
                            'title': 'Unsafe task',
                            'priority': 'critical',
                            'difficulty': 'medium',
                        }
                    ],
                    'schedule_items': [],
                    'academic_events': [],
                    'notes': [],
                },
            }

            with self.assertRaisesRegex(ValueError, 'недопустимое значение'):
                import_user_export_payload(user, payload, 'merge', db)

            self.assertEqual(
                db.query(Task).filter(Task.user_id == user.id).count(),
                0,
            )

    def test_csv_export_neutralizes_formula_cells(self):
        payload = {
            'version': 1,
            'exported_at': '2026-06-11T12:00:00',
            'user': {},
            'data': {
                'subjects': [
                    {
                        'id': 1,
                        'name': '=HYPERLINK("https://evil.example")',
                        'teacher': '+cmd',
                        'room': '@SUM(1,1)',
                        'color': '#8b5cf6',
                        'notes': '-2+3',
                    }
                ],
                'tasks': [],
                'schedule_items': [],
                'academic_events': [],
                'notes': [],
            },
        }

        archive = build_csv_export_archive(payload)
        with zipfile.ZipFile(archive) as exported_zip:
            with exported_zip.open('subjects.csv') as raw_csv:
                csv_text = TextIOWrapper(raw_csv, encoding='utf-8-sig').read()

        self.assertIn("'=HYPERLINK", csv_text)
        self.assertIn("'+cmd", csv_text)
        self.assertIn("'@SUM", csv_text)
        self.assertIn("'-2+3", csv_text)


if __name__ == '__main__':
    unittest.main()
