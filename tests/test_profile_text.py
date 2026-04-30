import unittest
from pathlib import Path


class ProfileTextTests(unittest.TestCase):
    def test_profile_route_contains_human_readable_russian_messages(self):
        text = Path('app/web/routes/profile.py').read_text(encoding='utf-8')
        self.assertIn('Пользователь с таким логином или email уже существует.', text)
        self.assertIn('Профиль обновлен.', text)

    def test_profile_template_contains_human_readable_russian_labels(self):
        text = Path('app/web/templates/profile/profile.html').read_text(encoding='utf-8')
        self.assertIn('Профиль', text)
        self.assertIn('Личный кабинет', text)
