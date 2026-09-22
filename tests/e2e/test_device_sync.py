from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def test_settings_link_modal_and_qr_url_work_end_to_end(e2e_page: Page):
    page = e2e_page
    console_errors: list[str] = []
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)

    page.goto('/')
    page.locator('.entry-v3-hero [data-entry-open]').click()
    page.locator('#entryDisplayName').fill('E2E Синхронизация')
    page.locator('#entryNextStep').click()
    page.locator('input[name="show_recovery"]').first.evaluate('(input) => input.value = "0"')
    page.locator('#entryCreateProfile').click()
    expect(page).to_have_url(re.compile(r'/dashboard(?:\?.*)?$'))

    page.goto('/profile')
    endpoint = page.locator('#profileConnectDevice').get_attribute('data-link-session-url')
    assert endpoint
    assert endpoint.endswith('/profile/devices/link-session')

    with page.expect_response(
        lambda response: response.request.method == 'POST'
        and response.url.endswith('/profile/devices/link-session')
    ) as response_info:
        page.locator('#profileConnectDevice').click()

    response = response_info.value
    assert response.status == 200
    assert 'application/json' in response.headers['content-type']
    payload = response.json()
    assert re.fullmatch(r'\d{6}', payload['code'])
    assert payload['expires_in_seconds'] == 300
    assert payload['link_url']
    assert payload['qr_data_uri'].startswith('data:image/svg+xml;base64,')

    expect(page.locator('[data-device-link-content]')).to_be_visible()
    expect(page.locator('[data-device-link-code]')).to_have_text(
        f"{payload['code'][:3]} {payload['code'][3:]}"
    )
    expect(page.locator('[data-device-link-qr]')).to_have_attribute(
        'src', re.compile(r'^data:image/svg\+xml;base64,')
    )
    assert console_errors == []

    phone_context = page.context.browser.new_context(viewport={'width': 390, 'height': 844})
    phone_page = phone_context.new_page()
    try:
        qr_response = phone_page.goto(payload['link_url'])
        assert qr_response is not None
        assert qr_response.status == 200
        expect(phone_page.get_by_role('heading', name='Подключить это устройство')).to_be_visible()
        expect(phone_page.locator('form[action="/link-device/confirm"]')).to_be_visible()
        expect(phone_page).to_have_url(re.compile(r'/link-device$'))
    finally:
        phone_context.close()
