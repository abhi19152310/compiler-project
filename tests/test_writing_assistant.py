"""Guidance must remain read-only and yield compiler-validated instructions."""

from copy import deepcopy
import json

import pytest

from app import create_app
from text2web import compile_source, compile_update
from text2web.nlp import NaturalInterpreter
from text2web.properties import COLORS, SIZES
from text2web.writing_assistant import catalog, instruction_at, suggest


PAGE = 'Create a page titled "Demo".'
NAV = 'Create a navigation bar with Home, About and Contact links.'


def compile_english(source):
    return compile_source(source, nlp_converter=NaturalInterpreter())


def utf16(value):
    return len(value.encode('utf-16-le')) // 2


def response(source, **kwargs):
    return suggest(source, utf16(source), **kwargs)


@pytest.mark.parametrize('instruction,prefix,wanted', [
    ('make a webpage named abhi', '', 'Create a page titled "abhi".'),
    ('make webpage background colour green', PAGE + '\n', 'Set the page background-color to "green".'),
    ('make background colour green', PAGE + '\n', 'Set the page background-color to "green".'),
    ('make a navigation bar with home,about,contact', PAGE + '\n', 'Create a navigation bar with "home", "about" and "contact" links.'),
    ('make it yellow', PAGE + '\n' + NAV + '\n', 'Set the navigation bar background-color to "yellow".'),
    ('make navigation bar yellow', PAGE + '\n' + NAV + '\n', 'Set the navigation bar background-color to "yellow".'),
    ('make the navigation bar dark green', PAGE + '\n' + NAV + '\n', 'Set the navigation bar background-color to "dark-green".'),
])
def test_suggested_wording_for_real_user_failures(instruction, prefix, wanted):
    result = response(prefix + instruction)
    candidates = [s for s in result['suggestions'] if s['ready']]
    assert wanted in [s['text'] for s in candidates]
    assert compile_english(prefix + wanted).success
    assert result['span']['text'] == instruction


def test_guidance_can_fix_each_line_without_changing_the_other_lines():
    source = 'make a webpage named abhi\nmake webpage background colour green\nmake a navigation bar with home,about,contact\nmake it yellow'
    for index in range(4):
        lines = source.splitlines(keepends=True)
        cursor = len(''.join(lines[:index])) + len(lines[index].rstrip('\n'))
        guidance = suggest(source, cursor)
        choice = next(s for s in guidance['suggestions'] if s['ready'])
        span = guidance['span']
        suffix = source[span['end']:]
        prefix = source[:span['start']]
        source = prefix + choice['replacement'] + suffix
        assert source.startswith(prefix) and source.endswith(suffix)
    compiled = compile_english(source)
    assert compiled.success, compiled.diagnostics
    assert compiled.page_properties['background-color'] == 'green'
    assert compiled.symbols[0].properties['background-color'] == 'yellow'
    assert all(e.properties['text-color'] == 'black' for e in compiled.symbols if e.type == 'link')


def test_same_line_periods_semicolons_and_quoted_punctuation():
    source = PAGE + ' make a navigation bar with "Home, first", "About. Us" and Contact; Add a heading that says "Welcome".'
    cursor = source.index(';')
    guidance = suggest(source, cursor)
    span = guidance['span']
    assert span['text'].startswith('make a navigation')
    choice = next(s for s in guidance['suggestions'] if s['ready'])
    assert not choice['replacement'].endswith('.')
    changed = source[:span['start']] + choice['replacement'] + source[span['end']:]
    result = compile_english(changed)
    assert result.success, result.diagnostics
    assert [e.text for e in result.symbols if e.type == 'link'] == ['Home, first', 'About. Us', 'Contact']
    assert changed.endswith('Add a heading that says "Welcome".')


def test_unicode_cursor_offsets_and_new_blank_line():
    prefix = 'Create a page titled "Campus \U0001f31f".\n'
    source = prefix + 'make background colour green.'
    result = response(source)
    assert result['span']['start'] == utf16(prefix)
    assert result['span']['end'] == utf16(source)
    assert result['span']['text'] == 'make background colour green.'
    blank = source + '\n'
    start, end, text = instruction_at(blank, utf16(blank))
    assert start == end == len(blank) and not text


def test_current_pronoun_uses_preceding_context_not_later_components():
    prefix = PAGE + '\n' + NAV + '\nAdd a button that says "Go".\n'
    source = prefix + 'make it blue.\nSet the navigation bar background-color to green.'
    guidance = suggest(source, len(prefix) + len('make it blue.'))
    choice = next(s for s in guidance['suggestions'] if s['ready'])
    assert choice['text'] == 'Set the button color to "blue".'


def test_page_template_does_not_prepend_a_duplicate_to_valid_source():
    guidance = suggest('  ' + PAGE, 0, template='page', values={'text': 'Duplicate'})
    assert not guidance['builder']['ready']
    assert 'already exists' in guidance['builder']['message']


def test_ambiguous_pronoun_is_not_guessed_and_previous_is_unchanged():
    initial = compile_english(PAGE + '\nCreate three cards for A, B and C.')
    snapshot = deepcopy(initial.debug_data())
    result = response('make it yellow', previous=initial, mode='update')
    assert result['suggestions'] and not result['suggestions'][0]['ready']
    assert 'Which component' in result['suggestions'][0]['message']
    assert initial.debug_data() == snapshot


def test_no_supported_title_is_invented_from_a_background_request():
    result = response(PAGE + '\nmake webpage background colour green')
    assert all(s['label'] != 'Page title' for s in result['suggestions'])


@pytest.mark.parametrize('partial', ['Add a', 'Create a', 'make a', 'Build a heading'])
def test_partial_instruction_completions(partial):
    result = response(PAGE + '\n' + partial)
    assert any(s['ready'] for s in result['suggestions'])
    assert all(compile_english(PAGE + '\n' + s['text']).success for s in result['suggestions'] if s['ready'])


def test_earlier_errors_are_flagged_instead_of_claiming_ready():
    result = response('Invalid earlier request.\nmake a navigation bar with Home and About')
    assert 'earlier instruction' in result['message']
    assert all(not s['ready'] for s in result['suggestions'])


@pytest.mark.parametrize('template,values', [
    ('navigation', {'text': 'Home, Courses, Contact'}),
    ('heading', {'text': 'Hello <students> & teachers', 'size': 'big'}),
    ('paragraph', {'text': 'Learn with us.'}), ('button', {'text': 'Register'}),
    ('image', {'src': 'https://example.com/image.jpg', 'alt': 'Campus'}),
    ('cards', {'text': 'Research, Teaching, Community'}), ('form', {}),
    ('background', {'target': 'the page', 'color': 'green'}),
    ('text-color', {'target': 'the page', 'color': 'blue'}), ('responsive', {}),
])
def test_templates_generate_valid_operations(template, values):
    result = response(PAGE, template=template, values=values)
    builder = result['builder']
    assert builder['ready'], builder
    assert builder['action'] == 'insert'
    assert compile_english(PAGE + '\n' + builder['text']).success


def test_page_builder_and_custom_color():
    result = response('', template='page', values={'text': 'My "New" Page'})
    assert result['builder']['ready'] and result['builder']['action'] == 'replace'
    assert compile_english(result['builder']['text']).page_tree.title == 'My "New" Page'
    result = response(PAGE + '\n' + NAV, template='background', values={'target': 'the navigation bar', 'color': '#ffff00'})
    assert result['builder']['ready']
    compiled = compile_english(PAGE + '\n' + NAV + '\n' + result['builder']['text'])
    assert compiled.success and compiled.symbols[0].properties['background-color'] == '#ffff00'


@pytest.mark.parametrize('template,values', [
    ('image', {'src': '', 'alt': ''}), ('image', {'src': 'javascript:alert(1)', 'alt': 'Bad'}),
    ('heading', {'size': 'massive', 'text': 'Title'}),
    ('background', {'target': 'the page', 'color': 'red;display:none'}),
    ('background', {'target': 'missing', 'color': 'green'}),
    ('rounded', {'target': 'the page', 'radius': '-1'}),
    ('not-a-template', {}), ('heading', {'text': 'Title', 'onclick': 'alert(1)'}),
])
def test_incomplete_unsafe_or_unsupported_builder_values(template, values):
    result = response(PAGE, template=template, values=values)
    assert not result['builder']['ready'] and result['builder']['message']


def test_rounded_builder_uses_existing_component_and_values_from_whitelist():
    result = response(PAGE + '\nAdd a button that says "Join".', template='rounded', values={'target': 'the button', 'radius': '18'})
    assert result['builder']['ready']
    assert result['builder']['text'] == 'Set the button border-radius to 18 pixels.'
    specs = {s['id']: s for s in catalog()}
    assert set(specs['background']['fields'][1]['options']) == set(COLORS)
    assert set(specs['heading']['fields'][1]['options']) == set(SIZES)


def test_followup_context_and_api_do_not_save_or_use_model(tmp_path):
    class ForbiddenProvider:
        def interpret(self, *args):
            raise AssertionError('Writing suggestions must never call a model.')
    app = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web', 'NLP_CONVERTER': NaturalInterpreter(ForbiddenProvider())})
    client = app.test_client()
    client.post('/', data={'source': PAGE + '\n' + NAV})
    key = client.get_cookie('text2web_workspace').value
    store = app.extensions['workspace_store']
    original = store.load(key)
    files = set(tmp_path.rglob('*'))
    result = client.post('/api/writing-assistant', json={'source': 'make it yellow', 'cursor': 14, 'mode': 'update'})
    assert result.status_code == 200 and result.json['suggestions'][0]['ready']
    assert result.headers['Cache-Control'] == 'no-store'
    assert store.load(key)['revision'] == original['revision']
    assert store.load(key)['result'].debug_data() == original['result'].debug_data()
    assert set(tmp_path.rglob('*')) == files
    initial = app.test_client()
    result = initial.post('/api/writing-assistant', json={'source': 'make a webpage named abhi', 'cursor': 25})
    assert result.json['suggestions'][0]['ready']
    assert initial.get_cookie('text2web_workspace') is None


@pytest.mark.parametrize('payload', [None, [], {}, {'source': 12}, {'source': 'a', 'cursor': -1},
    {'source': 'a', 'cursor': 2}, {'source': '', 'cursor': True}, {'source': '', 'mode': 'invalid'},
    {'source': '', 'values': []}, {'source': '', 'template': []}, {'source': 'x' * (128 * 1024 + 1)}])
def test_api_rejects_invalid_requests(tmp_path, payload):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'}).test_client()
    assert client.post('/api/writing-assistant', json=payload).status_code == 400
    assert not (tmp_path / 'web').exists()


def test_assistant_is_a_separate_section_and_untrusted_text_is_escaped(tmp_path):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'}).test_client()
    html = client.get('/').get_data(as_text=True)
    assert '<aside class="panel assistant-panel"' in html
    assert 'id="writing-assistant"' in html and 'assistant-catalog' in html
    source = 'make a webpage named <img src=x onerror=alert(1)>'
    result = client.post('/api/writing-assistant', json={'source': source, 'cursor': len(source)})
    text = result.json['suggestions'][0]['text']
    compiled = compile_english(text)
    assert compiled.success and '<img src=x' not in compiled.html



def test_workspace_uses_fresh_html_and_versioned_assets(tmp_path):
    import re
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'}).test_client()
    response = client.get('/')
    assert response.headers['Cache-Control'] == 'no-store'
    html = response.get_data(as_text=True)
    assert 'id="writing-assistant"' in html
    for filename in ['app.css', 'app.js', 'writing-assistant.js']:
        assert re.search(re.escape(filename) + r'\?v=\d+', html)
