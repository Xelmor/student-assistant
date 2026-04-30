from datetime import date, datetime, time
from types import SimpleNamespace
import unittest

from app.services.task_schedule_links import (
    get_task_anchor_datetime,
    get_task_calendar_event,
    parse_scheduled_for_date,
    validate_schedule_link,
)


class TaskScheduleLinkTests(unittest.TestCase):
    def test_parse_scheduled_for_date(self):
        self.assertEqual(parse_scheduled_for_date('2026-05-04'), date(2026, 5, 4))
        self.assertIsNone(parse_scheduled_for_date(''))

    def test_validate_schedule_link_rejects_wrong_weekday(self):
        schedule_item = SimpleNamespace(weekday=0)
        with self.assertRaises(ValueError):
            validate_schedule_link(schedule_item, date(2026, 5, 5))

    def test_anchor_datetime_prefers_deadline(self):
        task = SimpleNamespace(
            deadline=datetime(2026, 5, 4, 18, 0),
            scheduled_for_date=date(2026, 5, 4),
            schedule_item=SimpleNamespace(start_time=time(10, 0)),
        )
        self.assertEqual(get_task_anchor_datetime(task), datetime(2026, 5, 4, 18, 0))

    def test_calendar_event_uses_schedule_slot(self):
        schedule_item = SimpleNamespace(
            id=12,
            weekday=0,
            start_time=time(10, 0),
            end_time=time(11, 30),
            lesson_type='Практика',
            room='305',
            subject=SimpleNamespace(name='Математика'),
        )
        task = SimpleNamespace(
            id=7,
            title='Подготовить решение',
            description='Разобрать тему',
            priority='high',
            is_completed=False,
            deadline=None,
            scheduled_for_date=date(2026, 5, 4),
            schedule_item=schedule_item,
            schedule_item_id=12,
            subject=SimpleNamespace(name='Математика'),
        )

        event = get_task_calendar_event(task, datetime(2026, 5, 1, 9, 0))

        self.assertEqual(event['date'], date(2026, 5, 4))
        self.assertEqual(event['time_label'], '10:00 - 11:30')
        self.assertEqual(event['badge'], 'К занятию')
        self.assertEqual(event['room'], '305')


if __name__ == '__main__':
    unittest.main()
