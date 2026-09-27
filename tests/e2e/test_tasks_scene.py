import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width,height', [(1440, 1000), (1366, 768), (390, 844)])
def test_tasks_scene_sequence_and_spacing(e2e_page, width, height):
    page = e2e_page
    page.set_viewport_size({'width': width, 'height': height})
    page.goto('/', wait_until='networkidle')
    scene = page.locator('#product-demo')
    scene.scroll_into_view_if_needed()
    posts = []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    button = scene.locator('.entry-tasks-v2__form-add')
    expect(button).to_be_enabled(timeout=5000)
    # Longer than the old automatic sequence: nothing should happen without input.
    page.wait_for_timeout(5600)
    assert not scene.evaluate("(el) => el.classList.contains('is-created')")
    assert scene.locator('.entry-tasks-v2__form').evaluate('(el) => getComputedStyle(el).opacity') == '1'
    assert scene.locator('.entry-tasks-v2__new-slot').bounding_box()['height'] == 0
    button.click()
    expect(button).to_be_disabled()
    button.dispatch_event('click')  # Even a synthetic duplicate must be ignored.
    samples = scene.evaluate('''scene => new Promise(resolve => {
        const samples = [], start = performance.now();
        const find = cls => scene.querySelector('.entry-tasks-v2__' + cls);
        const rect = el => { const r = el.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height}; };
        function sample() {
            const form = find('form'), toast = find('toast'), row = find('task--new');
            samples.push({
                time:performance.now()-start, classes:scene.className,
                formOpacity:+getComputedStyle(form).opacity,
                formVisible:getComputedStyle(form).visibility !== 'hidden',
                form:rect(form), panel:rect(find('panel')), list:rect(find('list')),
                toast:rect(toast), toastOpacity:+getComputedStyle(toast).opacity,
                row:rect(find('new-slot')), rowPosition:getComputedStyle(row).position,
                firstTop:find('task:not(.entry-tasks-v2__task--new)').getBoundingClientRect().top,
                oldCheckOpacity:+getComputedStyle(find('task:not(.entry-tasks-v2__task--new) .entry-tasks-v2__check i')).opacity,
            });
            if (performance.now()-start > 3000) resolve(samples);
            else requestAnimationFrame(sample);
        }
        sample();
    })''')
    for s in samples:
        if s['formVisible'] and s['formOpacity'] > .1:
            assert s['form']['top'] >= s['panel']['bottom'] + 15
        if s['row']['height'] > 1:
            assert not s['formVisible'] or s['formOpacity'] < .01
        if 'is-toast-visible' in s['classes'] and s['toastOpacity'] > .1:
            assert 'is-complete' in s['classes']
            assert s['toast']['top'] >= s['panel']['bottom'] + 15
            assert s['toast']['left'] >= 0 and s['toast']['right'] <= width
        assert s['rowPosition'] not in ('absolute', 'fixed')
        assert s['oldCheckOpacity'] == 0
    growing = [s['row']['height'] for s in samples if 1 < s['row']['height'] < samples[-1]['row']['height'] - 1]
    assert len(growing) >= 2  # Observe intermediate heights without assuming a frame rate.
    assert growing == sorted(growing)
    assert not posts
    assert scene.locator('.entry-tasks-v2__task--new').count() == 1
    assert 'is-toast-visible' in samples[-1]['classes']
    assert 'is-step-toast' not in samples[-1]['classes']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert scene.locator('.entry-tasks-v2__form-float').evaluate('(el) => getComputedStyle(el).zIndex') == '20'
    assert scene.locator('.entry-tasks-v2__toast').evaluate('(el) => getComputedStyle(el).zIndex') == '30'


@pytest.mark.parametrize('key', ['Enter', 'Space'])
@pytest.mark.parametrize('motion', ['reduce', 'no-preference'])
def test_demo_keyboard_and_reduced_motion(e2e_page, key, motion):
    page = e2e_page
    page.emulate_media(reduced_motion=motion)
    page.goto('/', wait_until='networkidle')
    scene = page.locator('#product-demo')
    scene.scroll_into_view_if_needed()
    button = scene.locator('.entry-tasks-v2__form-add')
    expect(button).to_be_enabled(timeout=5000)
    assert scene.locator('.entry-tasks-v2__form-float').get_attribute('aria-hidden') == 'false'
    assert scene.locator('.entry-tasks-v2__new-slot').bounding_box()['height'] == 0
    posts = []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    button.focus()
    page.keyboard.press(key)
    if motion == 'reduce':
        assert scene.evaluate("(el) => el.classList.contains('is-toast-visible')")
    else:
        page.wait_for_function("() => document.querySelector('#product-demo').classList.contains('is-toast-visible')")
    expect(button).to_be_disabled()
    assert scene.locator('.entry-tasks-v2__form-float').evaluate('(el) => getComputedStyle(el).visibility') == 'hidden'
    assert scene.locator('.entry-tasks-v2__new-slot').bounding_box()['height'] > 0
    assert not posts


@pytest.mark.parametrize('cancel_animation', [False, True])
def test_demo_continues_without_animationend_or_observer(e2e_page, cancel_animation):
    page = e2e_page
    page.goto('/', wait_until='networkidle')
    scene = page.locator('#product-demo')
    scene.scroll_into_view_if_needed()
    button = scene.locator('.entry-tasks-v2__form-add')
    expect(scene).to_have_attribute('data-demo-state', 'waiting-for-add', timeout=5000)
    button.scroll_into_view_if_needed()
    assert button.evaluate('''el => {
        const r=el.getBoundingClientRect();
        return el.contains(document.elementFromPoint(r.x+r.width/2, r.y+r.height/2));
    }''')
    assert button.get_attribute('type') == 'button'
    if cancel_animation:
        scene.locator('.entry-tasks-v2__form').evaluate("el => el.style.setProperty('animation', 'none', 'important')")
    posts, events = [], []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    page.on('console', lambda msg: events.append(msg.text) if msg.type == 'debug' and msg.text.startswith('[tasks-demo]') else None)
    scene.evaluate("""el => {
        window.tasksDemoPhases = [];
        const phases = ['is-form-closing', 'is-created', 'is-checkbox-complete', 'is-complete', 'is-toast-visible'];
        new MutationObserver(() => {
            for (const phase of phases) {
                if (el.classList.contains(phase) && !window.tasksDemoPhases.includes(phase)) window.tasksDemoPhases.push(phase);
            }
        }).observe(el, {attributes:true, attributeFilter:['class']});
    }""")
    url = page.url
    button.click()
    expect(scene).to_have_attribute('data-demo-state', 'completing')
    button.dispatch_event('click')
    # Take the entire scene out of the viewport; continuation must not need IO.
    page.evaluate("scrollTo({top:0,behavior:'instant'})")
    expect(scene).to_have_attribute('data-demo-state', 'complete', timeout=5000)
    assert scene.locator('.entry-tasks-v2__form-float').get_attribute('aria-hidden') == 'true'
    assert scene.locator('.entry-tasks-v2__new-slot').get_attribute('aria-hidden') == 'false'
    assert scene.locator('.entry-tasks-v2__new-slot').bounding_box()['height'] > 0
    assert not posts
    assert page.url == url
    assert events == ['[tasks-demo] add clicked']
    assert page.evaluate('window.tasksDemoPhases') == [
        'is-form-closing', 'is-created', 'is-checkbox-complete', 'is-complete', 'is-toast-visible',
    ]
