import os
import unittest
from unittest.mock import patch

from app.core.config import DEVELOPMENT_SECRET_KEY, get_settings


class SettingsTests(unittest.TestCase):
    def test_development_uses_fallback_secret_key(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'development',
                'SECRET_KEY': 'short',
                'COOKIE_SECURE': 'false',
            },
            clear=False,
        ):
            settings = get_settings()

        self.assertEqual(settings.secret_key, DEVELOPMENT_SECRET_KEY)

    def test_production_requires_strong_secret_key(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'production',
                'SECRET_KEY': 'short',
                'COOKIE_SECURE': 'true',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()
