"""Isolated browser/UI status check; no real Telegram and no secret-bearing traces."""
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1440, 390])
def test_telegram_status_updates_existing_passwordless_space(browser, telegram_e2e_runtime, width):
    context = browser.new_context(base_url=telegram_e2e_runtime['base_url'], viewport={'width': width, 'height': 1000}, service_workers='block')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('/')
        csrf = page.locator('input[name="csrf_token"]').first.input_value()
        name = f'Telegram UI {uuid4().hex[:8]}'
        assert page.request.post('/start', form={'display_name': name, 'csrf_token': csrf}).ok
        page.goto('/profile#profile-telegram')
        card = page.locator('#profile-telegram')
        card.get_by_role('button', name='Подключить Telegram', exact=True).click()
        expect(page.locator('#telegramConnectionStatus')).to_contain_text('Ожидаем')
        expect(card.locator('a[href*="?start=link_"]')).to_be_visible()
        with sqlite3.connect(telegram_e2e_runtime['database_path']) as db:
            # Simulate the persisted result of the separately integration-tested webhook.
            db.execute('UPDATE users SET telegram_user_id = id + 90000, telegram_chat_id = id + 90000, telegram_link_code = NULL, telegram_link_code_expires_at = NULL WHERE display_name = ?', (name,))
        expect(card.locator('.profile-telegram-kicker')).to_have_text('Подключено', timeout=10000)
        expect(card.get_by_text('Связь сохранена.', exact=False)).to_be_visible()
        expect(card.locator('form[action="/profile/telegram/digest-test"] button')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert errors == []
        # Capture only the linked panel, after all single-use codes have disappeared.
        card.screenshot(path=str(Path('/tmp') / f'telegram-profile-{width}.png'))
    finally:
        context.close()
