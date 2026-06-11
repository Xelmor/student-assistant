from datetime import datetime, time, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.navbar_tools import build_navbar_payload


class NavbarToolsTests(unittest.TestCase):
    @staticmethod
    def _subject(subject_id=1, name='Математика'):
        return SimpleNamespace(
            id=subject_id,
            name=name,
            teacher='Иванов И.И.',
            room='Б-201',
            notes='Основной курс',
        )

    def test_payload_contains_real_entity_types_and_notification_groups(self):
        now = datetime(2026, 6, 10, 10, 0)
        subject = self._subject()
        schedule_item = SimpleNamespace(
            id=3,
            subject=subject,
            weekday=now.weekday(),
            start_time=time(11, 0),
            end_time=time(12, 30),
            lesson_type='Лекция',
            room='Б-201',
        )
        task = SimpleNamespace(
            id=5,
            title='Решить задачи',
            description='Глава 4',
            subject=subject,
            deadline=now + timedelta(hours=2),
            scheduled_for_date=None,
            schedule_item=None,
            is_completed=False,
        )
        event = SimpleNamespace(
            id=7,
            title='Экзамен',
            event_type='exam',
            event_date=now.date() + timedelta(days=2),
            start_time=time(9, 0),
            room='А-101',
            description='Итоговый экзамен',
            subject=subject,
        )
        note = SimpleNamespace(
            id=9,
            title='Формулы',
            content='Краткий конспект',
            link=None,
            subject=subject,
            created_at=now,
        )
        user = SimpleNamespace(
            id=11,
            tasks=[task],
            subjects=[subject],
            schedule_items=[schedule_item],
            academic_events=[event],
            notes=[note],
        )

        with patch('app.services.navbar_tools.current_time', return_value=now):
            payload = build_navbar_payload(user)

        self.assertEqual(payload['user_id'], 11)
        self.assertEqual(
            {item['type_label'] for item in payload['search']},
            {'Задача', 'Предмет', 'Пара', 'Событие', 'Заметка'},
        )
        self.assertTrue(any(item['id'].startswith('task-5') for item in payload['notifications']['today']))
        self.assertTrue(any(item['id'].startswith('class-3') for item in payload['notifications']['today']))
        self.assertTrue(any(item['id'].startswith('event-7') for item in payload['notifications']['soon']))


if __name__ == '__main__':
    unittest.main()
