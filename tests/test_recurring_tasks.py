from datetime import datetime
import unittest

from app.services.recurring_tasks import (
    RECURRENCE_CUSTOM_DAYS,
    RECURRENCE_DAILY,
    RECURRENCE_NONE,
    RECURRENCE_WEEKLY,
    calculate_next_deadline,
    get_recurrence_label,
    normalize_recurrence_settings,
    recurrence_requires_deadline,
)


class RecurringTaskTests(unittest.TestCase):
    def test_normalize_recurrence_settings(self):
        recurrence_type, recurrence_interval = normalize_recurrence_settings('daily', '')
        self.assertEqual(recurrence_type, RECURRENCE_DAILY)
        self.assertIsNone(recurrence_interval)

        recurrence_type, recurrence_interval = normalize_recurrence_settings('custom_days', '3')
        self.assertEqual(recurrence_type, RECURRENCE_CUSTOM_DAYS)
        self.assertEqual(recurrence_interval, 3)

    def test_custom_interval_validation(self):
        with self.assertRaises(ValueError):
            normalize_recurrence_settings('custom_days', '')

        with self.assertRaises(ValueError):
            normalize_recurrence_settings('custom_days', '1')

    def test_calculate_next_deadline(self):
        source = datetime(2026, 4, 29, 18, 30)

        self.assertEqual(
            calculate_next_deadline(source, RECURRENCE_DAILY, None),
            datetime(2026, 4, 30, 18, 30),
        )
        self.assertEqual(
            calculate_next_deadline(source, RECURRENCE_WEEKLY, None),
            datetime(2026, 5, 6, 18, 30),
        )
        self.assertEqual(
            calculate_next_deadline(source, RECURRENCE_CUSTOM_DAYS, 2),
            datetime(2026, 5, 1, 18, 30),
        )
        self.assertIsNone(calculate_next_deadline(source, RECURRENCE_NONE, None))

    def test_recurrence_labels_and_deadline_requirement(self):
        self.assertEqual(get_recurrence_label(RECURRENCE_DAILY, None), 'Каждый день')
        self.assertEqual(get_recurrence_label(RECURRENCE_WEEKLY, None), 'Каждую неделю')
        self.assertEqual(get_recurrence_label(RECURRENCE_CUSTOM_DAYS, 5), 'Каждые 5 дн.')
        self.assertIsNone(get_recurrence_label(RECURRENCE_NONE, None))

        self.assertTrue(recurrence_requires_deadline(RECURRENCE_DAILY))
        self.assertFalse(recurrence_requires_deadline(RECURRENCE_NONE))


if __name__ == '__main__':
    unittest.main()
