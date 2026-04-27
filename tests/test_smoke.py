from pathlib import Path
import unittest

from app.main import app
from app.web.dependencies import templates


class AppSmokeTests(unittest.TestCase):
    @staticmethod
    def _template_dir() -> Path:
        return Path(templates.env.loader.searchpath[0])

    def test_expected_routes_exist(self):
        paths = {route.path for route in app.routes}
        expected = {
            '/',
            '/login',
            '/register',
            '/dashboard',
            '/subjects',
            '/tasks',
            '/schedule',
            '/calendar',
            '/notes',
            '/profile',
            '/manifest.webmanifest',
            '/service-worker.js',
        }
        self.assertTrue(expected.issubset(paths))

    def test_template_root_exists(self):
        template_dir = self._template_dir()
        self.assertTrue(template_dir.exists())
        self.assertTrue((template_dir / 'base.html').exists())

    def test_feature_templates_exist(self):
        template_dir = self._template_dir()
        expected_templates = [
            'auth/index.html',
            'auth/login.html',
            'auth/register.html',
            'auth/forgot_password.html',
            'auth/reset_password.html',
            'dashboard/dashboard.html',
            'subjects/subjects.html',
            'tasks/tasks.html',
            'schedule/schedule.html',
            'calendar/calendar.html',
            'notes/notes.html',
            'profile/profile.html',
            'profile/local_profile.html',
        ]
        for relative_path in expected_templates:
            with self.subTest(template=relative_path):
                self.assertTrue((template_dir / relative_path).exists())

    def test_split_css_files_exist(self):
        css_dir = Path('app/static/css')
        expected_css = {
            'style.css',
            'base.css',
            'dashboard.css',
            'entities.css',
            'profile.css',
            'calendar.css',
            'responsive.css',
            'mobile.css',
        }
        self.assertTrue(css_dir.exists())
        self.assertTrue(expected_css.issubset({path.name for path in css_dir.iterdir()}))


if __name__ == '__main__':
    unittest.main()
