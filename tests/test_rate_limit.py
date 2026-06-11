from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.core.rate_limit import auth_rate_limiter, enforce_rate_limit


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        auth_rate_limiter.clear()
        self.request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))

    def tearDown(self):
        auth_rate_limiter.clear()

    def test_limit_returns_429_and_retry_after(self):
        enforce_rate_limit(
            self.request,
            scope='test-login',
            limit=2,
            window_seconds=60,
        )
        enforce_rate_limit(
            self.request,
            scope='test-login',
            limit=2,
            window_seconds=60,
        )

        with self.assertRaises(HTTPException) as raised:
            enforce_rate_limit(
                self.request,
                scope='test-login',
                limit=2,
                window_seconds=60,
            )

        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn('Retry-After', raised.exception.headers)

    def test_discriminators_use_separate_buckets(self):
        enforce_rate_limit(
            self.request,
            scope='identity',
            discriminator='first',
            limit=1,
            window_seconds=60,
        )
        enforce_rate_limit(
            self.request,
            scope='identity',
            discriminator='second',
            limit=1,
            window_seconds=60,
        )


if __name__ == '__main__':
    unittest.main()
