from __future__ import annotations

import logging

import httpx

from .config import settings


logger = logging.getLogger(__name__)


class ApiClientError(Exception):
    pass


class NotLinkedError(ApiClientError):
    pass


class StudentAssistantApiClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=httpx.Timeout(15.0),
            headers={'X-Bot-Api-Token': settings.api_token},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        chat_id: int | None = None,
        json: dict | None = None,
        params: dict | None = None,
    ):
        request_params = dict(params or {})
        if chat_id is not None:
            request_params['chat_id'] = chat_id
        response = await self._client.request(method, path, params=request_params or None, json=json)
        if response.status_code == 404:
            raise NotLinkedError('Telegram account is not linked.')
        if response.is_error:
            detail = response.text
            logger.warning('API request failed: %s %s -> %s %s', method, path, response.status_code, detail)
            raise ApiClientError(detail)
        return response.json()

    async def get_me(self, chat_id: int):
        return await self._request('GET', '/api/v1/telegram/me', chat_id=chat_id)

    async def link_telegram(self, code: str, chat_id: int, telegram_username: str | None):
        return await self._request(
            'POST',
            '/api/v1/telegram/link/confirm',
            json={'code': code, 'chat_id': chat_id, 'telegram_username': telegram_username},
        )

    async def get_subjects(self, chat_id: int):
        return await self._request('GET', '/api/v1/telegram/subjects', chat_id=chat_id)

    async def get_tasks(self, chat_id: int, status: str = 'active', limit: int = 20):
        response = await self._client.get(
            '/api/v1/telegram/tasks',
            params={'chat_id': chat_id, 'status': status, 'limit': limit},
            headers={'X-Bot-Api-Token': settings.api_token},
        )
        if response.status_code == 404:
            raise NotLinkedError('Telegram account is not linked.')
        if response.is_error:
            raise ApiClientError(response.text)
        return response.json()

    async def get_deadlines(self, chat_id: int, limit: int = 10):
        response = await self._client.get(
            '/api/v1/telegram/deadlines',
            params={'chat_id': chat_id, 'limit': limit},
            headers={'X-Bot-Api-Token': settings.api_token},
        )
        if response.status_code == 404:
            raise NotLinkedError('Telegram account is not linked.')
        if response.is_error:
            raise ApiClientError(response.text)
        return response.json()

    async def get_notes(self, chat_id: int, limit: int = 10):
        return await self._request('GET', '/api/v1/telegram/notes', chat_id=chat_id, params={'limit': limit})

    async def get_schedule(self, chat_id: int, scope: str = 'week'):
        response = await self._client.get(
            '/api/v1/telegram/schedule',
            params={'chat_id': chat_id, 'scope': scope},
            headers={'X-Bot-Api-Token': settings.api_token},
        )
        if response.status_code == 404:
            raise NotLinkedError('Telegram account is not linked.')
        if response.is_error:
            raise ApiClientError(response.text)
        return response.json()

    async def create_task(self, chat_id: int, payload: dict):
        return await self._request('POST', '/api/v1/telegram/tasks', chat_id=chat_id, json=payload)

    async def get_reminders(self, chat_id: int):
        return await self._request('GET', '/api/v1/telegram/reminders', chat_id=chat_id)

    async def update_reminders(self, chat_id: int, payload: dict):
        return await self._request('PUT', '/api/v1/telegram/reminders', chat_id=chat_id, json=payload)
