"""Real editor interaction, separate panel, safe replacements and mobile layout."""

import os
from threading import Thread

import pytest

from app import create_app

BROWSER = os.environ.get('TEXT2WEB_BROWSER')
pytestmark = pytest.mark.skipif(not BROWSER, reason='Set TEXT2WEB_BROWSER for Writing Assistant interaction tests.')


@pytest.fixture(scope='module')
def browser():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        instance = engine.chromium.launch(executable_path=BROWSER, headless=True)
        yield instance
        instance.close()


@pytest.fixture
def workspace(browser, tmp_path):
    from werkzeug.serving import make_server
    app = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'})
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{server.server_port}')
    yield page, tmp_path
    page.close()
    server.shutdown()
    thread.join(timeout=5)
    assert not errors


def select_instruction(editor, text):
    editor.evaluate('''(n, text) => {
      n.focus();
      const position = n.value.indexOf(text) + text.length;
      n.setSelectionRange(position, position);
      n.dispatchEvent(new Event('select'));
    }''', text)


def test_correct_real_request_and_followup_without_editor_overlay(workspace):
    from playwright.sync_api import expect
    page, _ = workspace
    editor = page.locator('#source')
    assert page.locator('#writing-assistant').evaluate('(n) => !n.closest("#compile-form") && !n.closest(".source-editor")')
    bounds = page.locator('.workspace').evaluate('''n => [".editor-panel", ".assistant-panel", ".preview-panel"].map(s => {
      const r = n.querySelector(s).getBoundingClientRect(); return {x:r.x, right:r.right};
    })''')
    assert bounds[0]['right'] <= bounds[1]['x'] and bounds[1]['right'] <= bounds[2]['x']
    original = 'make a webpage named abhi.\nmake webpage background colour green.\nmake a navigation bar with home,about,contact.\nmake it yellow.'
    editor.fill(original)
    for index, instruction in enumerate(original.splitlines()):
        before = editor.input_value().splitlines()
        select_instruction(editor, instruction)
        expect(page.locator('#assistant-current-text')).to_have_text(instruction)
        button = page.locator('#assistant-suggestions button').first
        expect(button).to_be_enabled()
        # Live guidance has not silently modified the editor.
        assert editor.input_value().splitlines() == before
        button.click()
        after = editor.input_value().splitlines()
        assert before[:index] == after[:index] and before[index + 1:] == after[index + 1:]
        assert '..' not in after[index]
    page.locator('#compile-button').click()
    page.get_by_text('Compilation successful', exact=True).wait_for()
    frame = page.frame_locator('iframe')
    assert frame.locator('nav').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(255, 255, 0)'
    assert frame.locator('body').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(22, 101, 52)'
    main_before = page.locator('#source').input_value()
    followup = page.locator('#followup-source')
    followup.fill('make it orange')
    expect(page.locator('#assistant-editor')).to_have_text('Helping with: follow-up instruction')
    expect(page.locator('#assistant-suggestions button').first).to_be_enabled()
    page.locator('#assistant-suggestions button').first.click()
    assert 'orange' in followup.input_value()
    assert page.locator('#source').input_value() == main_before
    page.get_by_role('button', name='Apply follow-up', exact=True).click()
    page.get_by_text('Compilation successful', exact=True).wait_for()
    assert page.frame_locator('iframe').locator('nav').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(255, 165, 0)'


def test_templates_custom_color_and_missing_image_fields(workspace):
    from playwright.sync_api import expect
    page, tmp_path = workspace
    editor = page.locator('#source')
    editor.fill('')
    page.get_by_role('button', name='Page', exact=True).click()
    page.locator('#assistant-field-text').fill('Abhi')
    insert = page.locator('#assistant-insert')
    expect(insert).to_be_enabled()
    assert editor.input_value() == ''
    insert.click()
    assert editor.input_value() == 'Create a page titled "Abhi".'
    page.get_by_role('button', name='Heading', exact=True).click()
    page.locator('#assistant-field-text').fill('Welcome <Abhi> & friends')
    expect(insert).to_be_enabled()
    expect(insert).to_have_text('Insert instruction')
    insert.click()
    assert editor.input_value().endswith('Add a big heading that says "Welcome <Abhi> & friends".')
    page.get_by_role('button', name='Background', exact=True).click()
    page.locator('#assistant-field-target').select_option('the page')
    page.locator('#assistant-field-color').select_option('custom')
    page.locator('#assistant-hex').fill('#ffff00')
    expect(insert).to_be_enabled()
    insert.click()
    assert '#ffff00' in editor.input_value()
    page.get_by_role('button', name='Image', exact=True).click()
    expect(insert).to_be_disabled()
    expect(page.locator('#assistant-builder-note')).to_contain_text('image url or filename')
    page.locator('#assistant-field-src').fill('javascript:alert(1)')
    page.locator('#assistant-field-alt').fill('Portrait')
    expect(page.locator('#assistant-builder-note')).to_contain_text('safe relative path')
    expect(insert).to_be_disabled()
    # User-provided copy is always displayed as text inside the assistant.
    assert page.locator('#writing-assistant img').count() == 0
    assert not (tmp_path / 'web').exists()
    assert not (tmp_path / 'workspaces.sqlite3').exists()


def test_stale_suggestion_cannot_overwrite_new_text(workspace):
    from playwright.sync_api import expect
    page, _ = workspace
    editor = page.locator('#source')
    editor.fill('make a webpage named Old')
    button = page.locator('#assistant-suggestions button').first
    expect(button).to_be_enabled()
    # Even a programmatic edit without an input event invalidates the snapshot.
    editor.evaluate('n => {n.value = "Create a page titled \\"New\\"."; n.setSelectionRange(n.value.length,n.value.length);}')
    expected = editor.input_value()
    button.click()
    assert editor.input_value() == expected


@pytest.mark.parametrize('width', [375, 768, 1200])
def test_assistant_layout_at_smaller_viewports(workspace, width):
    page, _ = workspace
    page.set_viewport_size({'width': width, 'height': 950})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#writing-assistant').is_visible()
    panel = page.locator('#writing-assistant').bounding_box()
    editor = page.locator('.editor-panel').bounding_box()
    assert panel['y'] >= editor['y'] + editor['height']



def test_partial_create_shows_suggestions_and_no_empty_column(workspace):
    from playwright.sync_api import expect
    page, _ = workspace
    editor = page.locator('#source')
    editor.fill('create a webpage called abhi.\ncreate')
    expect(page.locator('#assistant-suggestions button').first).to_be_enabled()
    expect(page.locator('#writing-assistant')).to_be_visible()
    # An older cached template without the panel must retain a two-column layout.
    page.locator('#writing-assistant').evaluate('(n) => n.remove()')
    dimensions = page.locator('.workspace').evaluate('(n) => ({columns:getComputedStyle(n).gridTemplateColumns.split(" ").length, gap:parseFloat(getComputedStyle(n).columnGap), editor:n.querySelector(".editor-panel").getBoundingClientRect().right, preview:n.querySelector(".preview-panel").getBoundingClientRect().x})')
    assert dimensions['columns'] == 2
    assert abs(dimensions['preview'] - dimensions['editor'] - dimensions['gap']) < 1
