"""Optional real-browser checks. Set TEXT2WEB_BROWSER to a Chrome executable."""

import os
from pathlib import Path

import pytest

from text2web import compile_source
from text2web.codegen import write_output

ROOT = Path(__file__).resolve().parents[1]
BROWSER = os.environ.get('TEXT2WEB_BROWSER')
pytestmark = pytest.mark.skipif(not BROWSER, reason='Set TEXT2WEB_BROWSER to run real Chrome viewport checks.')


@pytest.fixture(scope='module')
def browser():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        instance = engine.chromium.launch(executable_path=BROWSER, headless=True)
        yield instance
        instance.close()


@pytest.mark.parametrize('name', ['service-landing', 'personal-portfolio', 'contact-page', 'college-event'])
@pytest.mark.parametrize('width', [375, 768, 1440])
def test_page_viewports(browser, name, width, tmp_path):
    result = compile_source((ROOT / 'examples' / (name + '.sp')).read_text(encoding='utf-8'))
    assert result.success, result.diagnostics
    write_output(result, tmp_path, asset_root=ROOT / 'examples')
    page = browser.new_page(viewport={'width': width, 'height': 1000})
    try:
        page.goto((tmp_path / 'index.html').as_uri())
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflows horizontally'
        assert page.locator('main').count() == 1
        if name == 'service-landing':
            cards = page.locator('.card').evaluate_all('(nodes) => nodes.map(n => {const b = n.getBoundingClientRect(); return {x:b.x, y:b.y, height:b.height, width:b.width};})')
            assert len(cards) == 3
            if width <= 640:
                assert abs(cards[0]['x'] - cards[1]['x']) < 1
                assert cards[1]['y'] >= cards[0]['y'] + cards[0]['height']
                assert page.locator('nav').evaluate('(n) => getComputedStyle(n).flexDirection') == 'column'
            else:
                assert max(c['y'] for c in cards) - min(c['y'] for c in cards) < 1
                assert max(c['height'] for c in cards) - min(c['height'] for c in cards) < 1
            assert all(c['width'] > 0 for c in cards)
        if name == 'college-event':
            assert page.locator('img').evaluate('(n) => n.complete && n.naturalWidth > 0 && n.getBoundingClientRect().width <= n.parentElement.clientWidth')
        if name == 'contact-page':
            assert page.locator('input[type=email]').get_attribute('required') is not None
            assert page.locator('button[type=submit]').is_disabled()
            assert page.locator('form').get_attribute('inert') is not None
        # file:// stylesheets load, but Chrome forbids reading their CSSOM.
        assert page.locator('body').evaluate('(n) => getComputedStyle(n).margin') == '0px'
    finally:
        page.close()


def test_english_review_workflow_in_browser(browser, tmp_path):
    from threading import Thread
    from werkzeug.serving import make_server
    from app import create_app
    app = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'})
    server = make_server('127.0.0.1', 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    try:
        page.goto(f'http://127.0.0.1:{server.server_port}')
        page.locator('#source').fill('Create a web page called Review Day. Add a green navbar with Home, About and Contact. Add a large heading saying Welcome to Review Day.')
        page.locator('#compile-button').click()
        page.get_by_text('Compilation successful', exact=True).wait_for()
        assert page.locator('#followup-form').count() == 1
        frame = page.frame_locator('iframe')
        assert frame.locator('nav').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(22, 101, 52)'
        original_id = frame.locator('nav').get_attribute('id')
        page.locator('#followup-source').fill('Change the navbar background to dark green and add a Register button below the heading then make the button rounded.')
        page.get_by_role('button', name='Apply follow-up').click()
        page.get_by_text('Compilation successful', exact=True).wait_for()
        frame = page.frame_locator('iframe')
        assert frame.locator('nav').get_attribute('id') == original_id
        assert frame.locator('nav').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(20, 83, 45)'
        assert frame.get_by_role('button', name='Register').evaluate('(n) => getComputedStyle(n).borderRadius') == '12px'
        page.set_viewport_size({'width': 375, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#followup-source').fill('Implement authentication.')
        page.get_by_role('button', name='Apply follow-up').click()
        page.get_by_text('Compilation failed', exact=True).wait_for()
        assert page.locator('iframe').count() == 0
        page.get_by_role('link', name='Open saved page', exact=True).click()
        assert page.frame_locator('iframe').locator('nav').get_attribute('id') == original_id
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
