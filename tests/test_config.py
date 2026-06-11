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

    def test_production_rejects_documentation_secret_placeholder(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'production',
                'SECRET_KEY': 'replace_with_a_unique_random_string_at_least_32_chars_long',
                'COOKIE_SECURE': 'true',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_production_rejects_wildcard_allowed_hosts(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'production',
                'SECRET_KEY': 'a-secure-production-secret-key-that-is-long-enough',
                'COOKIE_SECURE': 'true',
                'ALLOWED_HOSTS': '*',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_production_requires_https_public_base_url(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'production',
                'SECRET_KEY': 'a-secure-production-secret-key-that-is-long-enough',
                'COOKIE_SECURE': 'true',
                'ALLOWED_HOSTS': 'student-assistant.example.com',
                'PUBLIC_BASE_URL': 'http://student-assistant.example.com',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_session_max_age_has_safe_bounds(self):
        with patch.dict(
            os.environ,
            {
                'APP_ENV': 'development',
                'SESSION_MAX_AGE_SECONDS': '60',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()
