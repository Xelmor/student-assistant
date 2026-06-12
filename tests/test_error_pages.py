import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app


class ErrorPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

        @cls.app.get('/__error-test/403')
        async def forbidden_test_route():
            raise HTTPException(
                status_code=403,
                detail='private authorization reason that must stay hidden',
            )

        @cls.app.get('/__error-test/429')
        async def rate_limit_test_route():
            raise HTTPException(status_code=429, detail='Too many requests.')

        @cls.app.get('/__error-test/500')
        async def server_error_test_route():
            raise RuntimeError(
                'SECRET_TOKEN=do-not-render /Users/private/project/database.py SQL SELECT'
            )

    def test_404_returns_custom_page_and_correct_status(self):
        with TestClient(self.app, raise_server_exceptions=False) as client:
            response = client.get('/this-page-does-not-exist')

        self.assertEqual(response.status_code, 404)
        self.assertIn('Страница не найдена', response.text)
        self.assertIn('data-error-back', response.text)
        self.assertNotIn('Not Found', response.text)

    def test_403_returns_safe_custom_page_and_correct_status(self):
        with TestClient(self.app, raise_server_exceptions=False) as client:
            response = client.get('/__error-test/403')

        self.assertEqual(response.status_code, 403)
        self.assertIn('Нет доступа', response.text)
        self.assertIn('href="/login"', response.text)
        self.assertNotIn('private authorization reason', response.text)

    def test_500_returns_safe_custom_page_without_technical_details(self):
        with TestClient(self.app, raise_server_exceptions=False) as client:
            response = client.get('/__error-test/500')

        self.assertEqual(response.status_code, 500)
        self.assertIn('Что-то пошло не так', response.text)
        self.assertIn('data-error-reload', response.text)
        self.assertNotIn('SECRET_TOKEN', response.text)
        self.assertNotIn('/Users/private', response.text)
        self.assertNotIn('SQL SELECT', response.text)
        self.assertNotIn('Traceback', response.text)
        self.assertNotIn('RuntimeError', response.text)

    def test_other_http_errors_keep_standard_behavior(self):
        with TestClient(self.app, raise_server_exceptions=False) as client:
            response = client.get('/__error-test/429')

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {'detail': 'Too many requests.'})


if __name__ == '__main__':
    unittest.main()
