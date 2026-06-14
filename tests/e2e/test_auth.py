from __future__ import annotations

import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def test_user_can_register_logout_and_login(e2e_page: Page, base_url: str):
    username = f'e2e_user_{uuid4().hex[:10]}'
    email = f'{username}@example.com'
    password = 'TestPassword123!'

    e2e_page.goto('/register')
    expect(e2e_page.get_by_test_id('register-form')).to_be_visible()
    e2e_page.get_by_test_id('register-username-input').fill(username)
    e2e_page.get_by_test_id('register-email-input').fill(email)
    e2e_page.get_by_test_id('register-password-input').fill(password)
    e2e_page.get_by_test_id('register-submit').click()

    expect(e2e_page).to_have_url(re.compile(r'/dashboard(?:\?.*)?$'))
    expect(e2e_page.get_by_test_id('dashboard-page')).to_be_visible()
    expect(e2e_page.get_by_test_id('current-user-name')).to_have_text(username)

    onboarding_skip = e2e_page.get_by_test_id('onboarding-skip')
    if onboarding_skip.is_visible():
        onboarding_skip.click()
        confirm = e2e_page.get_by_test_id('confirm-dialog-submit')
        expect(confirm).to_have_text('Пропустить')
        confirm.click()
        expect(e2e_page).to_have_url(re.compile(r'/dashboard(?:\?.*)?$'))
        expect(e2e_page.get_by_test_id('onboarding-skip')).to_have_count(0)

    e2e_page.get_by_test_id('profile-menu-toggle').click()
    e2e_page.get_by_test_id('logout-button').click()
    expect(e2e_page).to_have_url(f'{base_url}/')

    e2e_page.goto('/login')
    expect(e2e_page.get_by_test_id('login-form')).to_be_visible()
    e2e_page.get_by_test_id('login-input').fill(email)
    e2e_page.get_by_test_id('login-password-input').fill(password)
    e2e_page.get_by_test_id('login-submit').click()

    expect(e2e_page).to_have_url(re.compile(r'/dashboard(?:\?.*)?$'))
    expect(e2e_page.get_by_test_id('dashboard-page')).to_be_visible()
    expect(e2e_page.get_by_test_id('current-user-name')).to_have_text(username)
