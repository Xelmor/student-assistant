import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1366, 390])
def test_calendar_modes_navigation_filters_and_save(e2e_page, width):
    page = e2e_page
    page.set_viewport_size({'width': width, 'height': 900 if width == 1366 else 844})
    if width == 390:
        page.emulate_media(reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('/')
    csrf = page.locator('[name="csrf_token"]').first.input_value()
    assert page.request.post('/start', form={'display_name': 'Проверка календаря', 'csrf_token': csrf}).ok
    page.goto('/calendar')
    csrf = page.locator('[name="csrf_token"]').first.input_value()
    # Real endpoints, isolated temporary E2E database; no production records.
    for title, day, hour in [
        ('Экзамен без времени', '2026-12-31', ''),
        ('Утренний экзамен', '2026-12-31', '09:00'),
        ('Консультация', '2026-12-31', '12:00'),
        ('Вечерний экзамен', '2026-12-31', '18:00'),
        ('Событие нового года', '2027-01-01', '10:00'),
    ]:
        assert page.request.post('/calendar/session/add', form={
            'csrf_token': csrf, 'title': title, 'event_date': day,
            'event_type': 'exam', 'start_time': hour, 'room': 'А-101',
        }).ok
    assert page.request.post('/tasks/add', form={
        'csrf_token': csrf, 'title': 'Задача на день', 'scheduled_for_date': '2026-12-31',
    }).ok
    page.goto('/calendar?selected=2026-12-31&view=month')
    main = page.locator('[data-calendar-view]')

    def check_state(view, selected):
        expect(main).to_have_attribute('data-calendar-view', view)
        expect(page.locator('.calendar-view-switch .is-active')).to_have_count(1)
        expect(page.locator('.calendar-view-switch .is-active')).to_have_attribute('data-calendar-view-link', view)
        assert parse_qs(urlparse(page.url).query)['selected'] == [selected]
        expect(page.locator('.calendar-quick-form [name="view"]')).to_have_value(view)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.calendar-quick-form').evaluate('''form => {
            const r = form.getBoundingClientRect();
            return [...form.querySelectorAll('input:not([type=hidden]),select,textarea')].every(el => {
                const c = el.getBoundingClientRect();
                return !c.width || (c.left >= r.left - 1 && c.right <= r.right + 1);
            });
        }''')
        if width == 390:
            assert main.evaluate('el => getComputedStyle(el).animationName') == 'none'

    check_state('month', '2026-12-31')
    day = page.locator('[data-calendar-month-day="2026-12-31"]')
    expect(day.locator('[data-month-event]:visible')).to_have_count(3)
    expect(day.locator('[data-calendar-more]')).to_have_text('Ещё 2')
    day.locator('[data-calendar-more]').click()
    expect(page.locator('#selected-day-panel [data-calendar-event]')).to_have_count(5)
    check_state('month', '2026-12-31')
    page.locator('[data-calendar-filter="exam"]').locator('..').click()
    expect(day.locator('[data-month-event]:visible')).to_have_count(1)
    expect(day.locator('[data-calendar-more]')).to_be_hidden()
    for view in ['week', 'agenda']:
        page.locator(f'[data-calendar-view-link="{view}"]').click()
        check_state(view, '2026-12-31')
        expect(main.locator('[data-event-group="exam"]:visible')).to_have_count(0)
        page.locator('#calendarResetFilters').click()
        if view == 'week' and width == 1366:
            expect(main.locator('.calendar-all-day-event')).to_have_count(2)
            expect(main.locator('.calendar-timeline-event')).to_have_count(4)
        if view == 'agenda':
            expect(main.locator('[data-calendar-agenda-day]:visible')).to_have_count(2)
            expect(main).to_contain_text('Без времени')
        main.scroll_into_view_if_needed()
        main.screenshot(path=f'/tmp/sa-calendar-{view}-{width}.png', animations='disabled')
        if view == 'week':
            page.locator('[data-calendar-filter="exam"]').locator('..').click()
    page.go_back()
    check_state('week', '2026-12-31')
    page.go_forward()
    check_state('agenda', '2026-12-31')
    page.locator('.calendar-mini-day[href*="selected=2027-01-01"]').click()
    check_state('agenda', '2027-01-01')
    page.reload()
    check_state('agenda', '2027-01-01')
    page.locator('.calendar-period-navigation [aria-label="Следующая неделя"]').click()
    check_state('agenda', '2027-01-08')
    expect(main.locator('[data-calendar-period-empty]')).to_be_visible()
    page.locator('.calendar-period-navigation [aria-label="Предыдущая неделя"]').click()
    check_state('agenda', '2027-01-01')
    page.locator('.calendar-mini-heading [aria-label="Следующий месяц"]').click()
    check_state('agenda', '2027-01-01')
    expect(main).to_contain_text('Событие нового года')

    form = page.locator('.calendar-quick-form')
    form.locator('[name="title"]').fill('Сохранение в повестке')
    form.locator('[name="start_time"]').fill('')
    form.locator('[name="end_time"]').fill('')
    form.locator('button[type="submit"]').click()
    check_state('agenda', '2027-01-01')
    expect(main).to_contain_text('Сохранение в повестке')
    edit = page.locator('#selected-day-panel .calendar-agenda-item').filter(has_text='Сохранение в повестке')
    edit.locator('summary').click()
    edit.locator('button[type="submit"]').first.click()
    check_state('agenda', '2027-01-01')
    for checkbox in page.locator('[data-calendar-filter]').all():
        if checkbox.is_checked():
            checkbox.locator('..').click()
    expect(main.locator('[data-calendar-period-empty]')).to_be_visible()
    page.locator('#calendarResetFilters').click()
    expect(main.locator('[data-calendar-period-empty]')).to_be_hidden()
    page.locator('[data-calendar-view-link="month"]').click()
    check_state('month', '2027-01-01')
    page.locator('.calendar-period-navigation [aria-label="Предыдущий месяц"]').click()
    check_state('month', '2026-12-01')
    main.scroll_into_view_if_needed()
    main.screenshot(path=f'/tmp/sa-calendar-month-{width}.png', animations='disabled')
    page.locator('.calendar-timeline-actions').get_by_text('Сегодня', exact=True).click()
    expect(main).to_have_attribute('data-calendar-view', 'month')
    expect(page.locator('.calendar-month-cell.is-today')).to_have_class(re.compile('is-selected'))
    assert not errors
