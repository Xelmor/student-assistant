import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('profile_type', ['local', 'account'])
def test_settings_logout_confirms_and_disables_autologin(e2e_page: Page, base_url: str, profile_type: str):
    page = e2e_page
    if profile_type == 'local':
        page.goto('/')
        csrf = page.locator('input[name="csrf_token"]').first.input_value()
        response = page.request.post('/start', form={'display_name': 'Проверка выхода', 'csrf_token': csrf})
        assert response.ok
    else:
        page.goto('/register')
        username = f'logout_{uuid4().hex[:10]}'
        page.get_by_test_id('register-username-input').fill(username)
        page.get_by_test_id('register-email-input').fill(f'{username}@example.com')
        page.get_by_test_id('register-password-input').fill('TestPassword123!')
        page.get_by_test_id('register-submit').click()
        page.wait_for_url('**/dashboard')

    page.goto('/profile')
    page.locator('[data-accent-option="green"]').click()
    logout_requests = []
    page.on('request', lambda request: logout_requests.append(request)
            if request.method == 'POST' and request.url.endswith('/logout') else None)
    logout = page.get_by_test_id('settings-logout')
    expect(logout).to_have_text('Выйти')
    assert logout.evaluate('(button) => button.closest("form") === button.closest("main").lastElementChild')

    logout.click()
    expect(page.locator('#confirmDialogTitle')).to_have_text('Выйти из Student Assistant?')
    expect(page.get_by_test_id('confirm-dialog-submit')).to_have_text('Выйти')
    page.get_by_role('button', name='Отмена', exact=True).click()
    expect(page.locator('#confirmDialog')).to_be_hidden()
    expect(page).to_have_url(f'{base_url}/profile')
    assert not logout_requests

    logout.click()
    page.get_by_test_id('confirm-dialog-submit').click()
    expect(page).to_have_url(f'{base_url}/')
    expect(page.locator('body')).to_have_class(re.compile('entry-v3-page'))
    assert len(logout_requests) == 1
    assert all(cookie['name'] != 'sa_device_profile' for cookie in page.context.cookies())
    assert page.evaluate('localStorage.getItem("studentAssistant.accentColor")') == 'green'
    page.reload()
    expect(page).to_have_url(f'{base_url}/')
    page.goto('/dashboard')
    expect(page).not_to_have_url(f'{base_url}/dashboard')
