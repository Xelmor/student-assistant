import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def background_position(page):
    return page.evaluate('''() => ({
        x: scrollX, y: scrollY,
        heroTop: document.querySelector('.entry-v3-hero').getBoundingClientRect().top,
    })''')


def assert_locked(page):
    assert page.evaluate('document.documentElement.scrollHeight === innerHeight')
    assert page.evaluate('getComputedStyle(document.body).position') == 'fixed'
    assert page.locator('.page-shell').evaluate('(el) => el.inert')


def assert_centered(page):
    panel = page.locator('.entry-v3-setup-panel').bounding_box()
    size = page.viewport_size
    assert abs(panel['x'] + panel['width'] / 2 - size['width'] / 2) <= 1
    assert abs(panel['y'] + panel['height'] / 2 - size['height'] / 2) <= 1


def assert_restored(page, position):
    page.wait_for_function('(y) => Math.abs(scrollY - y) < 1', arg=position)
    assert page.evaluate('getComputedStyle(document.body).position') != 'fixed'
    assert not page.locator('.page-shell').evaluate('(el) => el.inert')
    assert page.evaluate('document.documentElement.scrollHeight > innerHeight')


@pytest.mark.parametrize('size', [(1440, 900), (1512, 982), (1920, 1080), (1366, 768)])
def test_desktop_onboarding_locks_wheel_keys_and_restores_position(e2e_page, size):
    page = e2e_page
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    page.goto('/', wait_until='networkidle')
    # The hero remains clickable at a nonzero document offset.
    page.evaluate("scrollTo({top: 80, behavior: 'instant'})")
    saved = page.evaluate('scrollY')
    for _ in range(2):
        page.locator('.entry-v3-hero [data-entry-open]').click()
        expect(page.locator('#entryDisplayName')).to_be_focused()
        page.wait_for_function("() => getComputedStyle(document.querySelector('.entry-v3-setup-panel')).transform === 'none'")
        assert_locked(page)
        assert_centered(page)
        position = background_position(page)
        page.mouse.move(5, 5)
        # Large wheel deltas and small repeated deltas model wheel/trackpad input.
        for delta in [700, -700, 8, 12, 16, -12, -8]:
            page.mouse.wheel(0, delta)
        page.locator('.entry-v3-setup-close').focus()
        for key in ['PageDown', 'PageUp', 'End', 'Home']:
            page.keyboard.press(key)
        page.wait_for_timeout(200)
        assert background_position(page) == position
        assert_locked(page)
        page.locator('.entry-v3-setup-close').click()
        assert_restored(page, saved)
    page.mouse.move(5, 5)
    page.mouse.wheel(0, 400)
    page.wait_for_function('(y) => scrollY > y', arg=saved)


def test_small_screen_scrolls_only_panel_and_closes_with_x(e2e_page):
    page = e2e_page
    page.set_viewport_size({'width': 390, 'height': 500})
    page.goto('/', wait_until='networkidle')
    page.locator('.entry-v3-hero [data-entry-open]').scroll_into_view_if_needed()
    saved = page.evaluate('scrollY')
    page.locator('.entry-v3-hero [data-entry-open]').click()
    page.locator('#entryDisplayName').fill('Тест прокрутки')
    page.locator('#entryNextStep').click()
    expect(page.locator('[data-entry-step="2"]')).to_be_visible()
    page.wait_for_function("() => getComputedStyle(document.querySelector('.entry-v3-setup-panel')).transform === 'none'")
    assert_locked(page)
    assert_centered(page)
    panel = page.locator('.entry-v3-setup-panel')
    assert panel.evaluate('(el) => el.scrollHeight > el.clientHeight')
    position = background_position(page)
    panel.hover()
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => document.querySelector('.entry-v3-setup-panel').scrollTop > 0")
    page.mouse.wheel(0, 1000)
    page.wait_for_timeout(200)
    assert background_position(page) == position
    # X remains reachable by scrolling back inside the card.
    page.mouse.wheel(0, -1500)
    page.locator('.entry-v3-setup-close').click()
    assert_restored(page, saved)


def test_final_cta_restores_bottom_position_after_escape(e2e_page):
    page = e2e_page
    page.goto('/', wait_until='networkidle')
    button = page.locator('[data-entry-morph]')
    button.scroll_into_view_if_needed()
    button.evaluate('(el) => el.focus({preventScroll: true})')
    saved = page.evaluate('scrollY')
    page.keyboard.press('Enter')
    expect(page.locator('#entryDisplayName')).to_be_focused(timeout=5000)
    expect(page.locator('.entry-cta-portal')).to_have_count(0)
    assert_locked(page)
    assert_centered(page)
    assert page.evaluate("parseFloat(document.body.style.getPropertyValue('--entry-scroll-top'))") == -saved
    page.keyboard.press('Escape')
    assert page.evaluate('scrollY') == saved
    assert_restored(page, saved)
    expect(button).to_be_focused()


@pytest.mark.parametrize('motion', ['no-preference', 'reduce'])
def test_onboarding_completion_does_not_lock_next_page(e2e_page, motion):
    page = e2e_page
    page.emulate_media(reduced_motion=motion)
    page.goto('/', wait_until='networkidle')
    page.locator('.entry-v3-hero [data-entry-open]').click()
    page.locator('#entryDisplayName').fill('Новое пространство')
    page.locator('#entryNextStep').click()
    assert_locked(page)
    page.locator('#entryCreateProfile').click()
    expect(page.locator('body')).not_to_have_class(re.compile('.*entry-modal-open.*'))
    assert page.evaluate('getComputedStyle(document.body).position') != 'fixed'
    assert page.locator('html').evaluate("(el) => !el.classList.contains('entry-modal-open')")
    expect(page.locator('a.device-connect-button[href="/dashboard?welcome=1"]')).to_be_visible()


def test_mobile_touch_scroll_stays_inside_onboarding(browser, browser_name, base_url):
    if browser_name != 'chromium':
        pytest.skip('Touch gesture injection uses Chromium CDP')
    context = browser.new_context(
        viewport={'width': 390, 'height': 500}, is_mobile=True,
        has_touch=True, service_workers='block', base_url=base_url,
    )
    try:
        page = context.new_page()
        page.goto('/', wait_until='networkidle')
        button = page.locator('.entry-v3-hero [data-entry-open]')
        button.scroll_into_view_if_needed()
        saved = page.evaluate('scrollY')
        button.tap()
        page.locator('#entryDisplayName').fill('Мобильный тест')
        page.locator('#entryNextStep').tap()
        expect(page.locator('[data-entry-step="2"]')).to_be_visible()
        panel = page.locator('.entry-v3-setup-panel')
        panel.evaluate('(el) => el.scrollTop = 0')
        position = background_position(page)
        session = context.new_cdp_session(page)

        def swipe(x):
            session.send('Input.dispatchTouchEvent', {
                'type': 'touchStart', 'touchPoints': [{'x': x, 'y': 420}],
            })
            for y in [380, 320, 240, 160]:
                session.send('Input.dispatchTouchEvent', {
                    'type': 'touchMove', 'touchPoints': [{'x': x, 'y': y}],
                })
            session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})

        swipe(5)  # Outside the panel: the landing must stay fixed.
        page.wait_for_timeout(200)
        assert background_position(page) == position
        swipe(195)
        page.wait_for_function("() => document.querySelector('.entry-v3-setup-panel').scrollTop > 0")
        assert_locked(page)
        assert background_position(page) == position
        page.locator('.entry-v3-setup-close').tap()
        assert_restored(page, saved)
    finally:
        context.close()
