"""English interpretation, model boundaries, IR transactions and saved edits."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError

import pytest

from app import create_app
from text2web import compile_source, compile_update
from text2web.intents import IntentError, SCHEMA, intents_to_dsl, validate_intents
from text2web.nlp import NaturalInterpreter, OllamaProvider, interpreter_from_env
from text2web.offline import create, style
from text2web.natural import segment
from text2web.workspace import StaleRevision, WorkspaceStore

ROOT = Path(__file__).resolve().parents[1]


def natural(source):
    return compile_source(source, nlp_converter=NaturalInterpreter())


def valid(source):
    result = natural(source)
    assert result.success, [(d.phase, d.line, d.message) for d in result.diagnostics]
    return result


@pytest.mark.parametrize('instruction,title', [
    ('Create a web page called Abhishek.', 'Abhishek'),
    ('Build me a website named Techno Fest.', 'Techno Fest'),
    ('I need a homepage for our college festival.', 'our college festival'),
    ('Kindly design a webpage titled Robotics Showcase.', 'Robotics Showcase'),
    ('Could you generate a website called Student Symposium?', 'Student Symposium'),
    ('I would like a page for Astronomy Club.', 'Astronomy Club'),
    ('BUILD ME A WEBSITE NAMED Research Day.', 'Research Day'),
])
def test_title_paraphrases(instruction, title):
    result = valid(instruction)
    assert result.page_tree.title == title
    assert result.ast[0].kind == 'page'
    assert result.tokens and result.interpretations[0]['route'] == 'offline'


def test_multi_part_request_and_followup_preserve_ids_and_styles():
    initial = valid('Create a page titled Techno Fest. Add a navigation bar with Home, About and Contact. Make the navigation bar green. Add a large heading saying Welcome to Techno Fest.')
    snapshot = deepcopy(initial.debug_data())
    updated = compile_update(initial, 'Change the navbar background to dark green and add a Register button below the heading then make the button rounded.')
    assert updated.success, updated.diagnostics
    assert initial.debug_data() == snapshot
    assert [e.id for e in updated.symbols[:len(initial.symbols)]] == [e.id for e in initial.symbols]
    assert updated.symbols[0].properties['background-color'] == 'dark-green'
    assert [e.text for e in updated.symbols if e.type == 'link'] == ['Home', 'About', 'Contact']
    assert all(e.properties['text-color'] == 'white' for e in updated.symbols if e.type == 'link')
    assert updated.symbols[-1].properties['border-radius'] == '12px'
    assert 'Welcome to Techno Fest' in updated.html
    assert 'background-color: #14532d' in updated.css


def test_model_free_spelling_and_navbar_coloring():
    result = valid('Create a web page called Demo. Add a green naviagtion bar with Home, About and Contact. add green colour to navigation bar')
    assert result.symbols[0].type == 'nav'
    assert result.symbols[0].properties['background-color'] == 'green'


def test_segmentation_preserves_urls_decimals_quotes_and_lines():
    source = 'Create a page called "A. B and then add something".\nAdd a link labelled "Visit" to "https://example.com/A?q=1.5"; make the link rounded and then add a button saying "Go and see".'
    clauses = list(segment(source))
    assert [line for line, _ in clauses] == [1, 2, 2, 2]
    assert natural(source).success
    assert len(list(segment('Set the heading font-size to 1.5rem.'))) == 1


def test_ambiguous_types_and_pronouns_do_not_mutate_previous():
    initial = valid('Create a page called Choices. Add a button saying "First". Add a button saying "Second".')
    failed = compile_update(initial, 'Make the button rounded.')
    assert not failed.success and failed.diagnostics[0].phase == 'clarification'
    assert all('border-radius' not in e.properties for e in initial.symbols)
    group = valid('Create a page called Cards. Create three cards for A, B and C.')
    failed = compile_update(group, 'Make it blue.')
    assert not failed.success and failed.diagnostics[0].phase == 'clarification'


def test_focus_ordinal_and_directional_references():
    initial = valid('Create a page called Demo. Add a heading saying Welcome. Add a button saying Go below the heading.')
    updated = compile_update(initial, 'Make it blue.')
    assert updated.success and updated.symbols[-1].properties['color'] == 'blue'
    cards = valid('Create a page called Cards. Add a card. Add another card beside the first card.')
    assert len(cards.symbols) == 2
    changed = compile_update(cards, 'Make the first card blue.')
    assert changed.success and changed.symbols[0].properties['color'] == 'blue'
    images = valid('Create a page called Pictures. Add a heading that says "Photo". Add an image "logo.png" described as "Logo". Put it to the right of the heading.')
    changed = compile_update(images, 'Make the image on the right responsive for mobile.')
    assert changed.success and changed.symbols[-1].properties['responsive'] == 'true'


def test_missing_image_details_are_a_clarification():
    result = natural('Create a page called Demo. Show an image below the heading.')
    assert not result.success and result.diagnostics[0].phase == 'clarification'
    assert 'URL' in result.diagnostics[0].message
    result = natural('Create a page called Demo. Show an image on the right side of the heading.')
    assert not result.success and result.diagnostics[0].phase == 'clarification'


def test_put_can_introduce_a_component_when_text_is_supplied():
    result = valid('Create a page called Demo. Add a navbar with Home and About. Put a large heading saying Annual Symposium below the navbar.')
    assert result.symbols[-1].type == 'heading' and result.symbols[-1].text == 'Annual Symposium'
    assert result.ast[-1].kind == 'position' and result.ast[-1].target_id == result.symbols[0].id


def test_named_case_and_replacing_position_constraints():
    initial = valid('Create a page called Demo. Add a card named "Projects". Set "Projects" padding to 24 pixels. Add a heading saying Welcome. Add a button saying Go below the heading.')
    updated = compile_update(initial, 'Move the button above the heading.')
    assert updated.success, updated.diagnostics
    positions = [s for s in updated.ast if s.kind == 'position']
    assert len(positions) == 1 and positions[0].properties['position'] == 'above'


@pytest.mark.parametrize('source', ['Connect the form to a database.', 'Implement authentication.', 'Add JavaScript animations.'])
def test_unsupported_backend_operations(source):
    result = natural('Create a page called Demo. ' + source)
    assert not result.success and result.diagnostics[0].phase == 'unsupported'


@pytest.mark.parametrize('name', ['fest', 'complete', 'portfolio', 'college-event', 'contact-page', 'personal-portfolio', 'service-landing', 'natural-review'])
def test_all_valid_existing_examples_in_natural_mode(name):
    source = (ROOT / 'examples' / (name + '.sp')).read_text(encoding='utf-8')
    result = natural(source)
    assert result.success, [(d.phase, d.line, d.message) for d in result.diagnostics]


@pytest.mark.parametrize('data', [None, [], {}, {'operations': []}, {'operations': [{'op': []}]},
    {'operations': [{'op': 'execute', 'code': 'print(1)'}]},
    {'operations': [create('script', 'alert(1)')]},
    {'operations': [style('page', {'onclick': 'alert(1)'})]},
    {'operations': [style('page', {'color': 4})]},
    {'operations': [{'op': 'page', 'title': 'Demo', 'extra': True}]},
    {'operations': [{'op': 'page', 'title': ''}]},
])
def test_schema_rejects_untrusted_model_data(data):
    with pytest.raises(IntentError):
        intents_to_dsl(data)


def test_model_response_is_schema_checked_reparsed_and_semantically_validated():
    class Provider:
        def __init__(self, operations):
            self.operations = operations
            self.contexts = []
        def interpret(self, instruction, context):
            self.contexts.append(context)
            return {'operations': self.operations}
    provider = Provider([create('paragraph', 'A previously unseen phrasing was interpreted')])
    initial = valid('Create a page called Model demo. Add a heading saying Hello.')
    result = compile_update(initial, 'Could we include a short introduction beneath the welcome?', nlp_converter=NaturalInterpreter(provider))
    assert result.success and result.interpretations[-1]['route'] == 'model'
    assert provider.contexts[0]['title'] == 'Model demo'
    assert provider.contexts[0]['components'][0]['id'] == 'element1'
    assert result.tokens[-1]['type'] == 'STRING' and result.ast[-1].element_type == 'paragraph'
    invalid = Provider([create('link', 'Unsafe', {'href': 'javascript:alert(1)'})])
    failed = compile_update(initial, 'Use a fancy reference for this.', nlp_converter=NaturalInterpreter(invalid))
    assert not failed.success and any('href' in d.message for d in failed.diagnostics)
    injected = Provider([create('paragraph', '<script>alert(1)</script> & text')])
    result = compile_update(initial, 'Use unusual wording.', nlp_converter=NaturalInterpreter(injected))
    assert result.success and '<script>' not in result.html and '&lt;script&gt;' in result.html


def test_model_cannot_silently_guess_an_id_for_an_ambiguous_type():
    class GuessingProvider:
        def interpret(self, instruction, context):
            return {'operations': [style('element1', {'border-radius': '12px'})]}
    previous = valid('Create a page called Demo. Add a button saying Alpha. Add a button saying Beta.')
    result = compile_update(previous, 'Please gently soften the corners of the button.', nlp_converter=NaturalInterpreter(GuessingProvider()))
    assert not result.success and result.diagnostics[0].phase == 'clarification'
    assert 'multiple button' in result.diagnostics[0].message


class Response(BytesIO):
    pass


def envelope(data):
    return json.dumps({'message': {'content': json.dumps(data)}, 'done': True}).encode()


def test_ollama_payload_and_server_only_authorization():
    seen = []
    def opener(request, timeout):
        seen.append((request, timeout))
        return Response(envelope({'operations': [create('paragraph', 'Hello')]}))
    provider = OllamaProvider(model='test-local-model', api_key='server-secret', opener=opener)
    data = provider.interpret('Some novel description', {'components': []})
    assert data['operations'][0]['type'] == 'paragraph'
    request, timeout = seen[0]
    payload = json.loads(request.data)
    assert payload['format'] == SCHEMA and payload['stream'] is False
    assert payload['options']['temperature'] == 0 and timeout == 20
    assert 'server-secret' not in request.data.decode()
    assert request.get_header('Authorization') == 'Bearer server-secret'


@pytest.mark.parametrize('failure,phase,word', [
    (TimeoutError(), 'service', 'timed out'), (socket.timeout(), 'service', 'timed out'),
    (URLError('private-host'), 'service', 'unavailable'),
    (HTTPError('url', 429, 'private', {}, None), 'service', 'rate limited'),
    (HTTPError('url', 404, 'private', {}, None), 'service', 'not found'),
    (HTTPError('url', 500, 'private', {}, None), 'service', 'service'),
])
def test_model_service_failure_is_plain_and_private(failure, phase, word):
    def opener(*args, **kwargs):
        raise failure
    provider = OllamaProvider(model='model', opener=opener)
    initial = valid('Create a page called Model demo.')
    result = compile_update(initial, 'Some unique unsupported wording.', nlp_converter=NaturalInterpreter(provider))
    assert not result.success and result.diagnostics[0].phase == phase
    assert word in result.diagnostics[0].message
    assert 'private' not in result.diagnostics[0].message
    # The deterministic/offline route remains available during model outages.
    assert compile_update(initial, 'Add a heading saying Still working.', nlp_converter=NaturalInterpreter(provider)).success


@pytest.mark.parametrize('raw', [b'not JSON', b'{}', b'{"error":"private service detail"}',
    b'{"done":false,"message":{"content":"{}"}}',
    envelope({'operations': [{'op': 'execute'}]}), b'x' * 262145], ids=lambda value: f'bytes-{len(value)}')
def test_invalid_model_envelopes(raw):
    provider = OllamaProvider(model='model', opener=lambda *a, **k: Response(raw))
    with pytest.raises(IntentError):
        provider.interpret('A request', {})


def test_environment_model_configuration(monkeypatch):
    monkeypatch.setenv('TEXT2WEB_NLP_BACKEND', 'ollama')
    monkeypatch.setenv('TEXT2WEB_NLP_MODEL', 'test-model')
    monkeypatch.setenv('TEXT2WEB_NLP_TIMEOUT', '3')
    converter = interpreter_from_env()
    assert converter.provider.model == 'test-model' and converter.provider.timeout == 3
    monkeypatch.setenv('TEXT2WEB_NLP_BACKEND', 'unsupported')
    with pytest.raises(ValueError):
        interpreter_from_env()


def test_sqlite_roundtrip_and_revision_conflict(tmp_path):
    result = valid('Create a page called Stored. Add a heading saying Hello.')
    path = tmp_path / 'workspaces.sqlite3'
    store = WorkspaceStore(path)
    store.save('workspace', expected=0, result=result, source='original', build_id='a' * 32)
    recovered = WorkspaceStore(path).load('workspace')
    assert recovered['result'].debug_data() == result.debug_data()
    assert recovered['result'].html == result.html and recovered['revision'] == 1
    with pytest.raises(StaleRevision):
        store.save('workspace', expected=0, result=result, source='stale', build_id='b' * 32)
    assert store.load('workspace')['build_id'] == 'a' * 32


def test_web_followups_persist_and_failed_changes_leave_saved_page(tmp_path):
    app = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'})
    client = app.test_client()
    initial = client.post('/', data={'source': 'Create a web page called Review. Add a green navbar with Home and About.'})
    assert b'Compilation successful' in initial.data and b'Apply follow-up' in initial.data
    edited = client.post('/', data={'mode': 'update', 'revision': '1', 'source': 'Change the navbar background to dark green.'})
    assert b'Compilation successful' in edited.data and b'Revision 2' in edited.data
    failed = client.post('/', data={'mode': 'update', 'revision': '2', 'source': 'Implement authentication.'})
    assert b'Compilation failed' in failed.data and b'<iframe' not in failed.data
    restored = client.get('/')
    assert b'Revision 2' in restored.data and b'background-color: #14532d' in restored.data
    stale = client.post('/', data={'mode': 'update', 'revision': '1', 'source': 'Make the navbar blue.'})
    assert b'changed in another tab' in stale.data
    cookie = client.get_cookie('text2web_workspace')
    other_app = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'})
    other = other_app.test_client()
    other.set_cookie('text2web_workspace', cookie.value)
    assert b'Revision 2' in other.get('/').data
    fresh = app.test_client()
    assert b'<iframe' not in fresh.get('/').data


def test_web_followup_reuses_uploaded_images(tmp_path):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'}).test_client()
    initial = client.post('/', data={'source': 'Create a page called Images. Add an image "logo.png" described as "Logo".',
        'assets': (BytesIO(b'\x89PNG\r\n\x1a\nimage'), 'logo.png', 'image/png')})
    assert b'Compilation successful' in initial.data
    update = client.post('/', data={'mode': 'update', 'revision': '1', 'source': 'Make the image responsive for mobile.'})
    assert b'Compilation successful' in update.data
    assert len(list((tmp_path / 'web').glob('*/logo.png'))) == 2


def test_web_cannot_modify_without_workspace(tmp_path):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web'}).test_client()
    response = client.post('/', data={'mode': 'update', 'revision': '0', 'source': 'Make it blue.'})
    assert b'Create a page before' in response.data


def test_evaluation_golden_cases_and_pipeline_boundaries():
    from evaluation.run import matches, output_matches
    cases = json.loads((ROOT / 'evaluation/cases.json').read_text(encoding='utf-8'))
    for case in cases:
        result = natural(case['input'])
        if 'reject' in case:
            assert not result.success and result.html is None, case['id']
            assert any(d.phase == case['reject'] for d in result.diagnostics), case['id']
        else:
            assert matches(result, case) and output_matches(result, case), case['id']
            assert result.ast and result.tokens and result.page_tree is not None


def test_failed_semantics_and_raw_bad_selectors_never_crash():
    previous = valid('Create a page called Demo. Add a heading saying Hello.')
    for source in ['Set the heading color to "red;display:none".', 'configure "ordinal:heading:bad" "color" "blue"',
                   'configure "position:heading:diagonal" "color" "blue"']:
        result = compile_update(previous, source)
        assert not result.success and result.html is None
    assert previous.symbols[0].properties == {}
