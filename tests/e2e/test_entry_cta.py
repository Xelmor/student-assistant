import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def prepare_final_cta(page: Page, width=1440, reduced_motion='no-preference'):
    page.set_viewport_size({'width': width, 'height': 900})
    page.emulate_media(reduced_motion=reduced_motion)
    page.goto('/')
    button = page.get_by_role('button', name='Начать сейчас', exact=True)
    button.scroll_into_view_if_needed()
    return button


def assert_transition_clean(page: Page):
    expect(page.locator('.entry-cta-portal, .is-cta-running')).to_have_count(0)
    button = page.locator('[data-entry-morph]')
    expect(button).not_to_have_attribute('aria-busy', 'true')
    expect(button).not_to_have_attribute('aria-disabled', 'true')
    assert button.evaluate('(el) => el.style.getPropertyValue("--cta-width")') == ''
    assert button.evaluate('(el) => el.style.getPropertyValue("--cta-size")') == ''
    assert page.locator('.entry-v3-final h2').evaluate('(el) => getComputedStyle(el).opacity') == '1'


@pytest.mark.parametrize('width', [1440, 390])
def test_final_cta_morph_keyboard_repeat_click_and_existing_onboarding(e2e_page: Page, width):
    page = e2e_page
    button = prepare_final_cta(page, width)
    posts = []
    page.on('request', lambda request: posts.append(request) if request.method == 'POST' else None)
    button.focus()
    button.press('Enter')
    expect(button).to_have_attribute('aria-busy', 'true')
    expect(page.locator('#entrySetup')).to_have_attribute('aria-hidden', 'true')
    button.dispatch_event('click')
    button.press('Enter')
    page.wait_for_function('''() => {
        const ring = document.querySelector('.entry-cta-ring-progress');
        const offset = parseFloat(getComputedStyle(ring).strokeDashoffset);
        return offset > 1 && offset < 95;
    }''')
    box = button.bounding_box()
    assert abs(box['width'] - box['height']) < 1
    expect(page.locator('#entrySetup')).to_have_attribute('aria-hidden', 'true')
    assert not posts
    expect(page.locator('#entryDisplayName')).to_be_focused(timeout=4000)
    expect(page.locator('.entry-v3-setup-panel')).to_be_in_viewport(ratio=0.95)
    expect(page.locator('#entrySetupTitle')).to_have_text('Как тебя называть?')
    assert_transition_clean(page)
    assert not posts
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

    # Continue the existing form all the way through its existing /start handler.
    page.locator('#entryDisplayName').fill('Морф переход')
    page.locator('#entryDisplayName').press('Enter')
    expect(page.locator('[data-entry-step="2"]')).to_be_visible()
    page.locator('#entryCreateProfile').click()
    expect(page).to_have_url(re.compile(r'/dashboard(?:\?.*)?$'))
    assert len([request for request in posts if request.url.endswith('/start')]) == 1


def test_reduced_motion_opens_with_short_fade_and_cleans_up(e2e_page: Page):
    page = e2e_page
    button = prepare_final_cta(page, 390, 'reduce')
    button.focus()
    button.press('Space')
    expect(page.locator('.is-cta-running, .entry-cta-portal')).to_have_count(0)
    expect(page.locator('#entryDisplayName')).to_be_focused(timeout=1200)
    expect(page.locator('.entry-v3-setup-panel')).to_be_in_viewport(ratio=0.95)
    assert_transition_clean(page)
    page.keyboard.press('Escape')
    expect(button).to_be_focused()
    expect(button).to_be_in_viewport()
    expect(page.locator('#entrySetup')).to_have_attribute('aria-hidden', 'true')


def test_escape_cancels_morph_and_allows_retry(e2e_page: Page):
    page = e2e_page
    button = prepare_final_cta(page)
    button.click()
    expect(button).to_have_attribute('aria-busy', 'true')
    page.keyboard.press('Escape')
    assert_transition_clean(page)
    expect(page.locator('#entrySetup')).to_have_attribute('aria-hidden', 'true')
    expect(button).to_be_focused()
    button.press('Space')
    expect(page.locator('#entryDisplayName')).to_be_focused(timeout=4000)
    assert_transition_clean(page)


def test_other_start_control_keeps_immediate_onboarding(e2e_page: Page):
    page = e2e_page
    page.goto('/')
    page.locator('.entry-v3-hero [data-entry-open]').click()
    expect(page.locator('#entrySetup')).to_have_attribute('aria-hidden', 'false', timeout=500)
    expect(page.locator('.is-cta-running, .entry-cta-portal')).to_have_count(0)


def test_motion_preference_change_during_morph_removes_effects(e2e_page: Page):
    page = e2e_page
    button = prepare_final_cta(page)
    button.click()
    expect(button).to_have_attribute('aria-busy', 'true')
    page.emulate_media(reduced_motion='reduce')
    expect(page.locator('#entryDisplayName')).to_be_focused(timeout=1200)
    assert_transition_clean(page)
