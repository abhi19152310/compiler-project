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
    result = compile_update(initial, 'Could we include an intro reading: a previously unseen phrasing was interpreted?', nlp_converter=NaturalInterpreter(provider))
    assert result.success and result.interpretations[-1]['route'] == 'model'
    assert provider.contexts[0]['title'] == 'Model demo'
    assert provider.contexts[0]['components'][0]['id'] == 'element1'
    assert result.tokens[-1]['type'] == 'STRING' and result.ast[-1].element_type == 'paragraph'
    invalid = Provider([create('link', 'Unsafe', {'href': 'javascript:alert(1)'})])
    failed = compile_update(initial, 'Use a fancy reference called Unsafe for this.', nlp_converter=NaturalInterpreter(invalid))
    assert not failed.success and any('href' in d.message for d in failed.diagnostics)
    injected = Provider([create('paragraph', '<script>alert(1)</script> & text')])
    result = compile_update(initial, 'Use unusual wording: <script>alert(1)</script> & text', nlp_converter=NaturalInterpreter(injected))
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
    (HTTPError('url', 404, 'private', {}, None), 'service', 'no model named'),
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


def test_invalid_page_background_is_a_diagnostic_not_a_crash():
    initial = valid('Create a page called Bakery.')
    result = compile_update(initial, 'configure "page" "background-color" "soft-yellow"', nlp_converter=NaturalInterpreter())
    assert not result.success and 'supported color' in result.diagnostics[0].message


def test_prompt_examples_are_valid_operations_and_model_slips_are_tidied():
    from text2web.nlp import EXAMPLES, _tidy
    for message in EXAMPLES[1::2]:
        validate_intents(json.loads(message['content']))
    tidied = _tidy({'operations': [create('button', 'Go', parent='null'), {'op': 'attach', 'target': 'button', 'parent': 'body'}]})
    assert tidied == {'operations': [create('button', 'Go')]}
    shaded = _tidy({'operations': [style('page', {'background-color': 'light-yellow'}), style('page', {'color': 'light-blue'})]})
    assert [o['properties'] for o in shaded['operations']] == [{'background-color': 'yellow'}, {'color': 'light-blue'}]


class FixedProvider:
    def __init__(self, *operations):
        self.operations = list(operations)

    def interpret(self, instruction, context):
        return {'operations': deepcopy(self.operations)}


@pytest.mark.parametrize('instruction,operation', [
    ('Write some marketing text for us', create('paragraph', 'Fresh bread, baked with love every day')),
    ('Show off a picture of our storefront', create('image', '', {'src': 'storefront.jpg', 'alt': 'Our storefront'})),
    ('Link to our Instagram labelled Follow us', create('link', 'Follow us', {'href': 'https://instagram.com/made-up'})),
])
def test_model_may_not_invent_content(instruction, operation):
    initial = valid('Create a page called Bakery.')
    result = compile_update(initial, instruction, nlp_converter=NaturalInterpreter(FixedProvider(operation)))
    assert not result.success and result.diagnostics[0].phase == 'clarification'


def placed(result, kind):
    ids = {e.id: e for e in result.symbols}
    return [(s.properties['position'], ids[s.target_id].type) for s in result.ast
            if s.kind == 'position' and ids[s.resolved_id].type == kind]


@pytest.mark.parametrize('instruction,extra,direction', [
    ('Write a short line under the heading that says We bake daily', [], 'below'),
    ('Beneath the heading add a blurb: We bake daily', [], 'below'),
    ('Above the heading, add a line saying We bake daily', [], 'above'),
    # The model already placed it and only added a stray parent.
    ('Under the heading put a line saying We bake daily', [{'op': 'position', 'target': 'name:line', 'direction': 'below', 'relative_to': 'element1'}], 'below'),
])
@pytest.mark.parametrize('parent', ['element1', 'name:element1', 'heading'])
def test_placement_emitted_as_a_parent_becomes_a_position(instruction, extra, direction, parent):
    initial = valid('Create a page called Bakery. Add a heading saying Hello.')
    provider = FixedProvider(create('paragraph', 'We bake daily', {'name': 'line'} if extra else {}, parent), *extra)
    result = compile_update(initial, instruction, nlp_converter=NaturalInterpreter(provider))
    assert result.success, [d.message for d in result.diagnostics]
    paragraph = [e for e in result.symbols if e.type == 'paragraph'][0]
    assert paragraph.parent_id is None and placed(result, 'paragraph') == [(direction, 'heading')]


@pytest.mark.parametrize('instruction', [
    'Stick a line saying We bake daily onto the heading',  # no placement word: not guessed
    'Under the heading, or above it, add a line saying We bake daily',  # conflicting directions
])
def test_placement_repair_never_guesses_a_direction(instruction):
    initial = valid('Create a page called Bakery. Add a heading saying Hello.')
    provider = FixedProvider(create('paragraph', 'We bake daily', {}, 'element1'))
    result = compile_update(initial, instruction, nlp_converter=NaturalInterpreter(provider))
    assert not result.success and 'cannot contain' in result.diagnostics[0].message


def test_run_on_page_title_is_left_to_the_model_not_misread():
    from text2web.offline import interpret
    # Reported: the whole rest of the sentence became the page title.
    assert interpret('please build me a webpage called abhimall put a welcome heading') is None
    assert interpret('Create a page called Abhimall and add a heading saying Hi') is None
    assert interpret('Create a page called "Add a Smile"')['operations'][0]['title'] == 'Add a Smile'
    assert interpret('Build me a website named Techno Fest')['operations'][0]['title'] == 'Techno Fest'
    result = natural('please build me a webpage called abhimall put a welcome heading')
    assert not result.success and result.diagnostics[0].phase == 'clarification'


def test_reference_to_a_name_never_assigned_means_the_new_component():
    # Gemma's actual output: the button is created unnamed, then placed by a made-up name.
    initial = valid('Create a page called Bakery. Add a heading saying Hello.')
    provider = FixedProvider(create('button', 'Order Now'),
                             {'op': 'position', 'target': 'name:order-now-button', 'direction': 'below', 'relative_to': 'element1'})
    result = compile_update(initial, 'Under the title, drop in a button labelled Order Now', nlp_converter=NaturalInterpreter(provider))
    assert result.success, [d.message for d in result.diagnostics]
    assert placed(result, 'button') == [('below', 'heading')]


def test_component_placed_relative_to_itself_means_the_new_component():
    # Gemma's actual output: "element1 below element1" after creating a paragraph.
    initial = valid('Create a page called Bakery. Add a heading saying Hello.')
    provider = FixedProvider(create('paragraph', 'We bake every morning'),
                             {'op': 'position', 'target': 'element1', 'direction': 'below', 'relative_to': 'element1'})
    result = compile_update(initial, 'Write a short line under the heading that says We bake every morning', nlp_converter=NaturalInterpreter(provider))
    assert result.success, [d.message for d in result.diagnostics]
    assert placed(result, 'paragraph') == [('below', 'heading')]


def test_new_component_reference_repair_needs_exactly_one_new_component():
    initial = valid('Create a page called Bakery. Add a heading saying Hello.')
    provider = FixedProvider(create('button', 'Order Now'), create('button', 'Call Us'),
                             {'op': 'position', 'target': 'name:order-now-button', 'direction': 'below', 'relative_to': 'element1'})
    result = compile_update(initial, 'Under the title add buttons Order Now and Call Us', nlp_converter=NaturalInterpreter(provider))
    assert not result.success and 'order-now-button' in result.diagnostics[0].message


def test_placement_repair_keeps_real_containers():
    initial = valid('Create a page called Bakery. Add a heading saying Hello. Add a section.')
    provider = FixedProvider(create('paragraph', 'We bake daily', {}, 'section'))
    result = compile_update(initial, 'Under the heading, inside the section, add a line saying We bake daily', nlp_converter=NaturalInterpreter(provider))
    assert result.success
    section = [e for e in result.symbols if e.type == 'section'][0]
    assert [e.parent_id for e in result.symbols if e.type == 'paragraph'] == [section.id]


def test_model_content_taken_from_the_instruction_is_accepted():
    initial = valid('Create a page called Bakery.')
    provider = FixedProvider(create('link', 'Follow us', {'href': 'https://instagram.com/sweetcrumbs'}))
    result = compile_update(initial, 'Drop a link to https://instagram.com/sweetcrumbs labelled follow us!', nlp_converter=NaturalInterpreter(provider))
    assert result.success and result.interpretations[-1]['route'] == 'model'
    # The model may fix spacing and capitalisation of what the user wrote.
    provider = FixedProvider(create('nav', '', {'name': 'menu'}), create('link', 'Contact Us', {'href': '/contact-us'}, 'name:menu'))
    result = compile_update(initial, 'add a menu bar with fields "about","home","contactus"', nlp_converter=NaturalInterpreter(provider))
    assert result.success, [d.message for d in result.diagnostics]


def test_model_request_keeps_model_loaded_and_bounds_output():
    seen = []
    def opener(request, timeout):
        seen.append(json.loads(request.data))
        return Response(envelope({'operations': [create('paragraph', 'Hello')]}))
    OllamaProvider(model='model', opener=opener).interpret('Some novel description', {'components': []})
    payload = seen[0]
    assert payload['keep_alive'] and payload['options']['num_predict'] <= 1024
    assert [m['role'] for m in payload['messages']][:3] == ['system', 'user', 'assistant']
    assert json.loads(payload['messages'][-1]['content'])['instruction'] == 'Some novel description'


def gemini_envelope(text, finish='STOP', thought=None):
    parts = ([{'text': thought, 'thought': True}] if thought else []) + [{'text': text}]
    return json.dumps({'candidates': [{'content': {'role': 'model', 'parts': parts}, 'finishReason': finish}],
                       'usageMetadata': {'promptTokenCount': 900, 'candidatesTokenCount': 20}}).encode()


def test_gemma_request_shape_and_key_stays_in_header():
    from text2web.nlp import GemmaProvider
    seen = []
    def opener(request, timeout):
        seen.append((request, timeout))
        return Response(gemini_envelope(json.dumps({'operations': [create('paragraph', 'Hello')]})))
    provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='secret-key', opener=opener)
    data = provider.interpret('Some novel description', {'components': []})
    assert data['operations'][0]['text'] == 'Hello'
    request, timeout = seen[0]
    body = json.loads(request.data)
    assert request.full_url == 'https://generativelanguage.googleapis.com/v1beta/models/gemma-4-26b-a4b-it:generateContent'
    assert request.get_header('X-goog-api-key') == 'secret-key' and timeout == 30
    assert 'secret-key' not in request.full_url and 'secret-key' not in request.data.decode()
    assert 'operation schema' in body['systemInstruction']['parts'][0]['text']
    assert [c['role'] for c in body['contents']][:2] == ['user', 'model'] and body['contents'][-1]['role'] == 'user'
    assert json.loads(body['contents'][-1]['parts'][0]['text'])['instruction'] == 'Some novel description'
    assert body['generationConfig']['temperature'] == 0 and body['generationConfig']['responseMimeType'] == 'application/json'


def test_gemma_reply_parsing():
    from text2web.nlp import GemmaProvider
    operations = json.dumps({'operations': [create('heading', 'Hi')]})
    for reply in [gemini_envelope('```json\n' + operations + '\n```'), gemini_envelope(operations, thought='Let me think.')]:
        provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='k', opener=lambda *a, **k: Response(reply))
        assert provider.interpret('x', {})['operations'][0]['type'] == 'heading'
    for reply in [gemini_envelope(operations, finish='MAX_TOKENS'), gemini_envelope('not json'), b'{"candidates": []}',
                  gemini_envelope(json.dumps({'operations': [{'op': 'execute'}]}))]:
        provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='k', opener=lambda *a, **k: Response(reply))
        with pytest.raises(IntentError):
            provider.interpret('x', {})


def test_gemma_falls_back_once_when_json_mode_is_rejected():
    from text2web.nlp import GemmaProvider
    bodies = []
    def opener(request, timeout):
        body = json.loads(request.data)
        bodies.append(body)
        if 'responseMimeType' in body['generationConfig']:
            raise HTTPError('url', 400, 'Bad Request', {}, BytesIO(b'{"error": {"message": "JSON mode is not enabled for this model"}}'))
        return Response(gemini_envelope(json.dumps({'operations': [create('paragraph', 'Hello')]})))
    provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='k', opener=opener)
    assert provider.interpret('x', {})['operations'][0]['text'] == 'Hello'
    provider.interpret('y', {})
    assert ['responseMimeType' in b['generationConfig'] for b in bodies] == [True, False, False]


RATE_LIMITED = (b'{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [{"@type": '
                b'"type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "57s"}]}}')


def test_gemma_waits_for_the_stated_retry_delay_after_a_rate_limit():
    from text2web.nlp import GemmaProvider
    waits, calls = [], []
    def opener(request, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError('url', 429, 'Too Many Requests', {}, BytesIO(RATE_LIMITED))
        return Response(gemini_envelope(json.dumps({'operations': [create('paragraph', 'Hello')]})))
    provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='k', opener=opener, sleep=waits.append)
    assert provider.interpret('x', {})['operations'][0]['text'] == 'Hello'
    assert waits == [58] and len(calls) == 2


def test_gemma_gives_up_after_two_rate_limit_waits():
    from text2web.nlp import GemmaProvider
    waits = []
    def opener(request, timeout):
        raise HTTPError('url', 429, 'Too Many Requests', {}, BytesIO(RATE_LIMITED))
    provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='k', opener=opener, sleep=waits.append)
    with pytest.raises(IntentError, match='still reached after waiting'):
        provider.interpret('x', {})
    assert waits == [58, 58]


def test_model_context_is_compacted_without_changing_meaning():
    from text2web.nlp import _compact, _user_message
    context = {'title': 'T', 'focus': None, 'positions': [], 'components': [
        {'id': 'element1', 'type': 'nav', 'text': '', 'name': 'menu', 'parent': None, 'properties': {}},
        {'id': 'element2', 'type': 'link', 'text': 'Home', 'name': None, 'parent': 'element1', 'properties': {'href': '/'}}]}
    assert _compact(context) == {'title': 'T', 'components': [{'id': 'element1', 'type': 'nav', 'name': 'menu'},
        {'id': 'element2', 'type': 'link', 'text': 'Home', 'parent': 'element1', 'properties': {'href': '/'}}]}
    assert json.loads(_user_message('Do it', context))['instruction'] == 'Do it'


@pytest.mark.parametrize('code,word', [(400, 'GEMINI_API_KEY'), (403, 'not accepted'), (404, 'not found'), (429, 'quota'), (500, 'Gemini API')])
def test_gemma_service_errors_are_plain_and_private(code, word):
    from text2web.nlp import GemmaProvider
    def opener(*args, **kwargs):
        raise HTTPError('url', code, 'private', {}, BytesIO(b'{"error": "private detail secret-key"}'))
    initial = valid('Create a page called Model demo.')
    provider = GemmaProvider(model='gemma-4-26b-a4b-it', api_key='secret-key', opener=opener, sleep=lambda seconds: None)
    result = compile_update(initial, 'Some unique unsupported wording.', nlp_converter=NaturalInterpreter(provider))
    assert not result.success and result.diagnostics[0].phase == 'service' and word in result.diagnostics[0].message
    assert 'private' not in result.diagnostics[0].message and 'secret-key' not in result.diagnostics[0].message


def test_gemma_environment_and_env_file(monkeypatch, tmp_path):
    from text2web.nlp import GemmaProvider, load_env_file
    for key in ('TEXT2WEB_NLP_BACKEND', 'GEMINI_API_KEY', 'TEXT2WEB_NLP_MODEL', 'TEXT2WEB_GEMMA_MODEL', 'TEXT2WEB_NLP_TIMEOUT'):
        # Recorded by monkeypatch, so values load_env_file sets are removed afterwards.
        monkeypatch.setenv(key, '')
        monkeypatch.delenv(key)
    env = tmp_path / '.env'
    env.write_text('# comment\nTEXT2WEB_NLP_BACKEND=gemma\nGEMINI_API_KEY="from-file"\nTEXT2WEB_GEMMA_MODEL=gemma-4-31b-it\n', encoding='utf-8')
    monkeypatch.setenv('TEXT2WEB_GEMMA_MODEL', 'gemma-4-26b-a4b-it')  # the shell wins over the file
    load_env_file(env)
    converter = interpreter_from_env()
    assert isinstance(converter.provider, GemmaProvider) and converter.provider.model == 'gemma-4-26b-a4b-it'
    assert converter.label == 'Gemma API gemma-4-26b-a4b-it + offline English'
    # A shell override to Ollama never picks up the Gemma model name (the reported bug).
    monkeypatch.setenv('TEXT2WEB_NLP_BACKEND', 'ollama')
    assert interpreter_from_env().provider.model == 'qwen2.5:3b'
    assert interpreter_from_env().label == 'Ollama qwen2.5:3b + offline English'
    monkeypatch.setenv('TEXT2WEB_NLP_BACKEND', 'gemma')
    monkeypatch.delenv('GEMINI_API_KEY')
    env.write_text('TEXT2WEB_NLP_BACKEND=gemma\nGEMINI_API_KEY=\n', encoding='utf-8')
    load_env_file(env)
    with pytest.raises(ValueError, match='GEMINI_API_KEY'):
        interpreter_from_env()
    load_env_file(tmp_path / 'missing.env')  # a missing file is fine


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


def test_web_shows_each_sentence_next_to_its_dsl(tmp_path):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web', 'NLP_CONVERTER': NaturalInterpreter()}).test_client()
    page = client.post('/', data={'source': 'Create a web page called Trace.\nAdd a heading saying "<b>Hi</b>".\nAdd a green navbar with Home and About.'}).data.decode()
    pane = page[page.index('id="pane-interpretation"'):page.index('id="pane-normalized_input"')]
    assert pane.count('<tr class="trace-') == 3
    assert 'Add a green navbar with Home and About' in pane and 'Offline English' in pane
    assert 'component &#34;link&#34; &#34;About&#34;' in pane or 'component &quot;link&quot; &quot;About&quot;' in pane
    assert '<b>Hi</b>' not in pane and '&lt;b&gt;Hi&lt;/b&gt;' in pane
    failed = client.post('/', data={'source': 'Create a web page called Trace.\nImplement some wizardry.'}).data.decode()
    pane = failed[failed.index('id="pane-interpretation"'):failed.index('id="pane-normalized_input"')]
    assert 'Not understood' in pane and 'trace-message' in pane


def test_contrast_warning_is_shown_saved_and_cleared(tmp_path):
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path / 'web', 'NLP_CONVERTER': NaturalInterpreter()}).test_client()
    page = client.post('/', data={'source': 'Create a page called Bright.\nAdd a heading saying Hello.\nMake the heading yellow.'}).data.decode()
    assert 'Compilation successful' in page and '1 warning' in page and 'below the recommended' in page
    assert 'data-source-line="2"' in page  # the line that created the heading
    store = WorkspaceStore(tmp_path / 'workspaces.sqlite3')
    key = client.get_cookie('text2web_workspace').value
    assert [w.line for w in store.load(key)['result'].warnings] == [2]
    fixed = client.post('/', data={'mode': 'update', 'revision': '1', 'source': 'Make the heading black.'}).data.decode()
    assert 'Compilation successful' in fixed and 'below the recommended' not in fixed


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


@pytest.mark.parametrize('spelling', ['color', 'colour'])
@pytest.mark.parametrize('shade,foreground', [('yellow', 'black'), ('orange', 'black'), ('purple', 'white')])
def test_make_webpage_navbar_and_background_spellings(spelling, shade, foreground):
    result = valid(f'make a webpage named abhi. change the background {spelling} to {shade}. make a navbar with home,about,contact. make it {shade}. Add a paragraph that says "Welcome".')
    assert result.page_tree.title == 'abhi'
    assert result.page_properties == {'background-color': shade, 'text-color': foreground}
    nav = next(e for e in result.symbols if e.type == 'nav')
    assert nav.properties['background-color'] == shade
    assert all(e.properties['text-color'] == foreground for e in result.symbols if e.type == 'link')


@pytest.mark.parametrize('instruction', [
    'make background colour yellow', 'make webpage background colour yellow',
    'make the webpage background color yellow', 'change the background to yellow',
    'change background color to yellow', 'set the page background colour to yellow',
])
def test_background_wording(instruction):
    result = valid('make a webpage named abhi. ' + instruction + '.')
    assert result.page_properties['background-color'] == 'yellow'


@pytest.mark.parametrize('shade,foreground', [('yellow', '#111827'), ('orange', '#111827'), ('purple', '#ffffff')])
@pytest.mark.parametrize('expanded', [False, True])
def test_named_button_colors_in_both_renderers(shade, foreground, expanded):
    source = f'Create a page titled "Demo". Add a {shade} button that says "Go".'
    if expanded:
        source += ' Set the button padding to 12px.'
    result = compile_source(source)
    assert result.success, result.diagnostics
    assert f'color: {foreground}' in result.css


def test_automatic_page_foreground_survives_saved_followup():
    from dataclasses import asdict
    from text2web.workspace import restore
    first = valid('make a webpage named abhi. change the background to purple. Add a paragraph that says "Welcome".')
    updated = compile_update(restore(asdict(first)), 'change the background to yellow', nlp_converter=NaturalInterpreter())
    assert updated.success, updated.diagnostics
    assert updated.page_properties['text-color'] == 'black'
    explicit = compile_update(updated, 'Set the page text-color to white. change the background to yellow.', nlp_converter=NaturalInterpreter())
    assert explicit.success and any(w.phase == 'contrast' for w in explicit.warnings)


def test_incomplete_make_requests_clarify():
    for instruction, word in [('make a webpage', 'called'), ('make a navbar', 'labels'), ('change the background', 'color')]:
        result = natural(instruction)
        assert not result.success
        assert any(word in d.message for d in result.diagnostics), result.diagnostics
