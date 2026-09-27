from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def assert_layout(row, mobile=False):
    geometry = row.evaluate('''row => {
        const box = el => { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}; };
        const panel = row.querySelector('.tasks-edit-panel');
        const grid = row.querySelector('.tasks-edit-grid');
        return {row:box(row), panel:box(panel), main:box(row.querySelector('.tasks-task-main')),
            grid:box(grid), gap:getComputedStyle(grid).gap,
            fields:[...grid.children].map(box),
            controls:[...grid.querySelectorAll('input,select,textarea')].map(box),
            buttons:[...row.querySelectorAll('.tasks-edit-actions button')].map(box),
            overflow:document.documentElement.scrollWidth > innerWidth};
    }''')
    assert not geometry['overflow']
    assert geometry['main']['bottom'] <= geometry['panel']['y']
    assert geometry['gap'] == '16px'
    fields = geometry['fields']
    for field in fields[:2]:
        assert abs(field['width'] - geometry['grid']['width']) < 1
    assert fields[0]['bottom'] <= fields[1]['y']
    if mobile:
        for a, b in zip(fields, fields[1:]):
            assert a['bottom'] <= b['y']
    else:
        assert abs(fields[2]['width'] - fields[3]['width']) < 1
        assert abs(fields[2]['y'] - fields[3]['y']) < 1
        assert abs(fields[3]['x'] - fields[2]['right'] - 16) < 1
    for control in geometry['controls'] + geometry['buttons']:
        assert control['width'] > 0 and control['height'] > 0
        assert control['x'] >= geometry['panel']['x']
        assert control['right'] <= geometry['panel']['right'] + 1
        assert control['bottom'] <= geometry['panel']['bottom'] + 1
    for a, b in zip(geometry['controls'], fields):
        assert abs(a['width'] - b['width']) < 1


@pytest.mark.parametrize('width', [1440, 1366, 390])
def test_card_edit_cancel_save_and_views(e2e_page, width):
    page = e2e_page
    page.set_viewport_size({'width': width, 'height': 1000 if width > 400 else 844})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    # Only the fixture's temporary database is used, never the user's data.
    page.goto('/')
    csrf = page.locator('input[name="csrf_token"]').first.input_value()
    response = page.request.post('/start', form={'display_name': 'Проверка карточек', 'csrf_token': csrf})
    assert response.ok
    page.goto('/tasks')
    for title, priority in [('Алгебра: подготовить конспект', 'low'), ('Базы данных: лабораторная работа', 'high')]:
        form = page.locator('.tasks-create-form')
        form.locator('[name="title"]').fill(title)
        form.locator('[name="description"]').fill('Проверка формы редактирования в изолированном окружении.')
        form.locator('[name="priority"]').select_option(priority)
        form.locator('button[type="submit"]').click()
        expect(page.locator('.tasks-alert')).to_have_count(0)
    rows = page.locator('[data-task-item]')
    expect(rows).to_have_count(2)
    expect(page.locator('[data-task-group]')).to_have_count(1)
    page.locator('[data-task-view="compact"]').click()
    panel = page.locator('.tasks-list-panel')
    expect(panel).to_have_class(re.compile('is-grid-view'))
    first = rows.filter(has_text='Алгебра: подготовить конспект')
    second = rows.filter(has_text='Базы данных: лабораторная работа')
    first_id = first.get_attribute('id')
    second_id = second.get_attribute('id')
    first = page.locator(f'#{first_id}')
    second = page.locator(f'#{second_id}')
    # Allow motion-system entrance transforms to settle before measuring rows.
    page.wait_for_timeout(700)
    if width > 400:
        a, b = first.bounding_box(), second.bounding_box()
        assert abs(a['y'] - b['y']) < 1
        assert a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x']
    assert rows.evaluate_all("""rows => rows.every(row => {
        const boxes = [...row.children].filter(el => getComputedStyle(el).display !== 'none')
            .map(el => el.getBoundingClientRect());
        return boxes.every((a, i) => boxes.slice(i + 1).every(b =>
            a.right <= b.left + 1 || b.right <= a.left + 1 ||
            a.bottom <= b.top + 1 || b.bottom <= a.top + 1));
    })""")
    peer_height = second.bounding_box()['height']
    first.locator('.is-edit').click()
    expect(first).to_have_class(re.compile('is-editing'))
    expect(first.locator('.tasks-edit-panel')).to_be_visible()
    expect(second.locator('.tasks-edit-panel')).to_be_hidden()
    assert_layout(first, width == 390)
    for selector in ['.tasks-task-status', '.tasks-task-deadline', '.tasks-task-priority', '.tasks-task-actions']:
        expect(first.locator(selector)).to_be_hidden()
    a, b = first.bounding_box(), second.bounding_box()
    assert b['y'] >= a['y'] + a['height'] or a['y'] >= b['y'] + b['height']
    assert abs(b['height'] - peer_height) < 1
    assert first.evaluate("el => getComputedStyle(el).gridColumn") == '1 / -1'
    first.get_by_role('button', name='Отмена', exact=True).click()
    expect(first).not_to_have_class(re.compile('is-editing'))
    expect(first.locator('.tasks-edit-panel')).to_be_hidden()
    # Opening another task must also close a still-open form.
    first.locator('.is-edit').click()
    second.locator('.is-edit').click()
    expect(first.locator('.tasks-edit-panel')).to_be_hidden()
    expect(first).not_to_have_class(re.compile('is-editing'))
    expect(second).to_have_class(re.compile('is-editing'))
    assert_layout(second, width == 390)
    page.mouse.move(0, 0)
    expect(page.locator('.app-toast')).to_have_count(0, timeout=7000)
    page.wait_for_timeout(300)
    output = Path('/tmp') / f'sa-task-edit-open-{width}.png'
    if width > 400:
        second.screenshot(path=str(output), animations='disabled')
    else:
        second.locator('.tasks-task-main').scroll_into_view_if_needed()
        page.screenshot(path=str(output), animations='disabled')
        second.get_by_role('button', name='Сохранить изменения').scroll_into_view_if_needed()
        page.screenshot(path='/tmp/sa-task-edit-open-390-buttons.png', animations='disabled')
        assert second.locator('.tasks-edit-actions button').evaluate_all('''buttons => buttons.every(button => {
            const r = button.getBoundingClientRect();
            return button.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
        })''')
    form = second.locator('.tasks-edit-form')
    before = form.evaluate('el => Object.fromEntries(new FormData(el))')
    assert before['csrf_token']
    assert form.get_attribute('method') == 'post'
    edit_path = form.get_attribute('action')
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith(edit_path)) as saved:
        form.get_by_role('button', name='Сохранить изменения').click()
    assert saved.value.status == 302
    expect(second.locator('.tasks-edit-panel')).to_be_hidden()
    expect(second).not_to_have_class(re.compile('is-editing'))
    # Submit existing values unchanged; verify persistence and view restoration.
    assert second.locator('.tasks-edit-form').evaluate('el => Object.fromEntries(new FormData(el))') == before
    page.reload()
    expect(panel).to_have_class(re.compile('is-grid-view'))
    expect(page.locator('.tasks-edit-panel:not(.d-none)')).to_have_count(0)
    page.locator('#taskSortSelect').select_option('title')
    expect(rows.first.locator('.tasks-task-main > strong')).to_have_text('Алгебра: подготовить конспект')
    page.locator('#taskSortSelect').select_option('priority')
    expect(rows.first.locator('.tasks-task-main > strong')).to_have_text('Базы данных: лабораторная работа')
    page.locator('#taskSearchInput').fill('Алгебра')
    expect(page.locator('[data-task-item]:visible')).to_have_count(1)
    page.locator('#taskSearchInput').fill('')
    page.locator('[data-task-filter="done"]').click()
    expect(page.locator('[data-task-item]:visible')).to_have_count(0)
    page.locator('[data-task-filter="all"]').click()
    expect(page.locator('[data-task-item]:visible')).to_have_count(2)
    page.locator('[data-task-view="list"]').click()
    expect(panel).to_have_class(re.compile('is-list-view'))
    first.locator('.is-edit').click()
    expect(first.locator('.tasks-edit-panel')).to_be_visible()
    assert first.locator('.tasks-edit-form').evaluate('''form => {
        const r = form.getBoundingClientRect();
        return [...form.querySelectorAll('input:not([type=hidden]),select,textarea,button')].every(el => {
            const c = el.getBoundingClientRect();
            return c.x >= r.x - 1 && c.right <= r.right + 1;
        });
    }''')
    first.get_by_role('button', name='Отмена', exact=True).click()
    expect(first.locator('.tasks-edit-panel')).to_be_hidden()
    page.reload()
    expect(panel).to_have_class(re.compile('is-list-view'))
    assert not errors
