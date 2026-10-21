"""Expanded-language integration, semantic, security and output validity tests."""

import json
from pathlib import Path
from html.parser import HTMLParser

import pytest

from text2web import compile_source
from text2web.codegen import write_output
from text2web.english import component, configure
from text2web.properties import CSS_KEYS, ENUMS, LENGTHS

ROOT = Path(__file__).resolve().parents[1]


def compile_body(source):
    return compile_source('Create a page titled "Test".\n' + source)


def ok(source):
    result = compile_body(source)
    assert result.success, [(d.line, d.phase, d.message) for d in result.diagnostics]
    return result


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def tags(self, tag):
        return [attrs for name, attrs in self.nodes if name == tag]


@pytest.mark.parametrize('verb', ['Create', 'Add', 'Insert', 'Please create'])
@pytest.mark.parametrize('word', ['labelled', 'labeled', 'called', 'that says'])
def test_links_paraphrases_and_case_sensitive_url(verb, word):
    result = ok(f"{verb} a link {word} 'Visit GitHub' that opens https://github.com/SomeProject.\nOpen this external link in a new tab.")
    anchor = Document(result.html).tags('a')[0]
    assert anchor['href'] == 'https://github.com/SomeProject'
    assert anchor['target'] == '_blank'
    assert anchor['rel'] == 'noopener noreferrer'
    assert result.symbols[0].text == 'Visit GitHub'


def test_button_style_link_is_not_action_button():
    result = ok('Create a button-style link to the registration page.\nAdd a button that says "Action".')
    doc = Document(result.html)
    assert doc.tags('a')[0]['href'] == '/registration'
    assert doc.tags('a')[0]['class'] == 'button-link'
    assert doc.tags('button')[0]['type'] == 'button'


@pytest.mark.parametrize('href', ['', '#', 'javascript:alert(1)', 'data:text/html,x', '//evil.example', 'https://user:pass@example.com', 'https://', 'https://example.com:bad', '/a%0ab', '/%5cevil', 'file:///etc/passwd'])
def test_bad_destinations_block_generation(href):
    result = compile_body(component('link', 'Visit', {'href': href}))
    assert not result.success and result.html is None and result.css is None


def test_fragments_require_real_ids_and_escape_link_text():
    result = ok(component('section', '', {'id': 'about'}) + '\n' + component('link', '<script> & About', {'href': '#about'}))
    assert '<script>' not in result.html
    assert '&lt;script&gt; &amp; About' in result.html
    assert not compile_body(component('link', 'Missing', {'href': '#missing'})).success


@pytest.mark.parametrize('phrase', ['Add an image called', 'Create an image from', 'Insert an image called'])
def test_image_dimensions_and_responsive_aspect(phrase):
    result = ok(f"{phrase} 'https://example.com/Photo.jpg' with the description 'Company logo'.\nDisplay this image at 45 pixels wide and 60 pixels tall.\nMake the image responsive and keep its aspect ratio.")
    image = Document(result.html).tags('img')[0]
    assert image['width'] == '45' and image['height'] == '60'
    assert image['alt'] == 'Company logo'
    assert 'width: 45px' in result.css and 'height: auto' in result.css
    assert 'height: 60px' not in result.css


@pytest.mark.parametrize('source', ['', 'https://', 'https://a:wrong/a.png', 'https://user@example.com/a.png', '../a.png', 'file:///a.png', 'data:image/png;base64,abc'])
def test_bad_images(source):
    result = compile_body(component('image', 'Photo', {'src': source}))
    assert not result.success


def test_image_missing_description_and_explicit_decorative():
    result = compile_body("Add an image from 'https://example.com/photo.jpg'.")
    assert not result.success and any('description' in d.message for d in result.diagnostics)
    result = ok("Add a decorative image from 'https://example.com/photo.jpg'.")
    assert Document(result.html).tags('img')[0]['alt'] == ''


def test_logo_is_wrapped_in_named_link():
    result = ok(component('image', 'Company logo', {'src': 'logo.png', 'name': 'logo'}) + '\nMake the logo link to the homepage.')
    assert Document(result.html).tags('a')[0]['href'] == '/'
    assert result.symbols[0].parent_id == result.symbols[1].id
    assert result.page_tree.children[0].children[0].element_id == result.symbols[0].id


def test_linking_logo_keeps_its_nav_parent_and_left_alignment():
    result = ok('Create a navigation bar with Home and About links.\n' + component('image', 'Logo', {'src': 'logo.png', 'name': 'logo'}, 'nav') + '\nPut the logo on the left and the navigation links on the right.\nMake the logo link to the homepage.')
    wrapper = result.symbols[-1]
    assert wrapper.type == 'link' and wrapper.parent_id == result.symbols[0].id
    assert wrapper.properties['order'] == '-1'
    assert wrapper.properties['margin-right'] == 'auto'


def test_semantic_page_and_navigation_relationships():
    result = ok('Create a header at the top, the main content in the middle and a footer at the bottom.\nCreate a navigation bar with Home, About, Services and Contact links inside the header.\nAdd a heading that says "Welcome" inside the main.\nCreate a breadcrumb navigation.\nPlace the nav above the main.')
    doc = Document(result.html)
    assert len(doc.tags('main')) == 1
    assert len(doc.tags('header')) == len(doc.tags('footer')) == 1
    assert [a['href'] for a in doc.tags('a')] == ['/', '/about', '/services', '/contact']
    assert doc.tags('nav')[1]['aria-label'] == 'Breadcrumb'


def test_cards_batch_children_containment_and_reusable_styles():
    result = ok('Create three cards for Web Development, AI and Cloud Computing.\nEach card should have a short description "A service" and a button "Learn more".\nPut all the cards inside one container.\nGive all cards consistent spacing and rounded corners.')
    cards = [e for e in result.symbols if e.type == 'card']
    for card in cards:
        assert [e.type for e in result.symbols if e.parent_id == card.id] == ['heading', 'paragraph', 'button']
        assert card.parent_id == result.symbols[-1].id
    attrs = Document(result.html).tags('article')
    assert len({a['class'] for a in attrs}) == 1
    assert 'style=' not in result.html


@pytest.mark.parametrize('instructions', [
    'Add a card with rounded corners.',
    'Create a card that has rounded edges.',
    'Add a card. Give the card a corner radius of 12 pixels.',
])
def test_rounded_corner_paraphrases_are_equivalent(instructions):
    result = ok(instructions)
    canonical = ok('Add a card with rounded corners.')
    assert (result.html, result.css) == (canonical.html, canonical.css)


def test_nested_lists_and_table_escape_content():
    result = ok('Add an unordered list named "technologies".\nAdd a list item "Frontend" inside "technologies".\nSet it name to "frontend".\nAdd a bulleted list of "HTML", "CSS" inside "frontend".\nCreate a table with columns for Subject, Credits and Grade.\nAdd a row with "<script>", "4" and "A & B".')
    doc = Document(result.html)
    assert len(doc.tags('ul')) == 2 and len(doc.tags('li')) == 3
    assert len(doc.tags('th')) == len(doc.tags('td')) == 3
    assert all(a['scope'] == 'col' for a in doc.tags('th'))
    assert '&lt;script&gt;' in result.html and 'A &amp; B' in result.html


@pytest.mark.parametrize('key', sorted(LENGTHS))
def test_dimension_properties_and_paraphrases(key):
    result = ok(f'Add a container. Set the container {key} to 24 pixels.')
    assert f'{key}: 24px' in result.css
    invalid = compile_body(f'Add a container. Set the container {key} to -2 pixels.')
    assert not invalid.success


@pytest.mark.parametrize('key,value', [
    ('color', '#123456'), ('background-color', 'light-grey'), ('border-color', 'blue'),
    ('font-family', 'serif'), ('font-weight', '600'), ('text-align', 'center'),
    ('line-height', '1.8'), ('text-decoration', 'underline'), ('display', 'flex'),
    ('flex-direction', 'column'), ('flex-wrap', 'wrap'), ('align-items', 'center'),
    ('justify-content', 'space-between'), ('align-self', 'stretch'), ('columns', '3'),
    ('border-style', 'solid'), ('box-shadow', 'subtle'), ('transition', 'smooth'),
    ('background-image', 'https://example.com/bg.png'),
])
def test_css_whitelist_values(key, value):
    result = ok(component('container') + '\n' + configure('container', key, value))
    assert 'style-1' in result.html
    assert value in result.css or key in {'color', 'background-color', 'border-color', 'columns', 'box-shadow', 'transition'}


@pytest.mark.parametrize('key,value', [
    ('width', '0px'), ('height', '-1px'), ('font-size', '99999px'), ('gap', 'calc(1px + 1%)'),
    ('display', 'none; background:red'), ('color', 'red;display:none'), ('background-color', 'url(x)'),
    ('onclick', 'alert(1)'), ('position', 'fixed'), ('style', 'color:red'), ('srcdoc', '<script>'),
    ('background-image', 'https://example.com/a");color:red;/*'), ('line-height', '0.5'), ('columns', '0'),
])
def test_invalid_css_cannot_bypass_validation(key, value):
    result = compile_body(component('container', '', {key: value}))
    assert not result.success and result.html is None


def test_css_last_value_wins_and_property_order_is_deterministic():
    first = ok(component('card', '', {'padding': '12px', 'border-radius': '6px'}) + '\n' + configure('card', 'padding', '24px'))
    second = ok(component('card', '', {'border-radius': '6px', 'padding': '24px'}))
    assert (first.html, first.css) == (second.html, second.css)
    assert 'padding: 12px' not in first.css


def test_responsive_media_queries_and_no_unused_component_css():
    result = ok('Add a navigation bar with Home and About links.\nMake the navigation bar adapt to smaller screens.\nCreate three cards for A, B and C.\nPut all the cards inside one container.\nDisplay three cards in a row on desktop.\nStack the cards vertically on mobile.')
    assert '@media (max-width: 640px)' in result.css
    assert 'repeat(3, minmax(0, 1fr))' in result.css
    assert 'flex-direction: column' in result.css
    assert '.form {' not in result.css and '.table-scroll {' not in result.css


def test_all_form_controls_labels_validation_and_static_notice():
    result = ok('Create a contact form with name, email and message fields.\nMake the email field required.\nAdd a password field labelled "Password".\nAdd a checkbox field labelled "Agree".\n' + component('input', 'Morning', {'type': 'radio', 'name': 'time', 'value': 'am'}, 'form') + '\n' + component('input', 'Afternoon', {'type': 'radio', 'name': 'time', 'value': 'pm'}, 'form') + '\nAdd a dropdown for selecting a department with options Sales and Support.\nSet the email minlength to 3.')
    doc = Document(result.html)
    controls = doc.tags('input') + doc.tags('textarea') + doc.tags('select')
    labels = {a['for'] for a in doc.tags('label')}
    assert all(c['id'] in labels for c in controls)
    assert {c['type'] for c in doc.tags('input')} == {'text', 'email', 'password', 'checkbox', 'radio'}
    assert 'required' in next(c for c in controls if c.get('type') == 'email')
    assert len(doc.tags('option')) == 2
    assert doc.tags('button')[0]['type'] == 'submit' and 'disabled' in doc.tags('button')[0]
    assert 'inert' in doc.tags('form')[0]
    assert 'Submission, authentication and storage are not connected' in result.html


@pytest.mark.parametrize('source,expected', [
    (component('li', 'Orphan'), 'parent'),
    (component('table') + '\n' + component('paragraph', 'Bad', parent='table'), 'cannot contain'),
    (component('form') + '\n' + component('form', parent='form'), 'nested'),
    (component('input', 'Orphan'), 'inside a form'),
    (component('main') + '\n' + component('main'), 'Only one main'),
    (component('link', 'Outer', {'href': '/'}) + '\n' + component('button', 'Inner', parent='link'), 'interactive'),
    (component('card', '', {'name': 'x'}) + '\n' + component('card', '', {'name': 'x'}), 'Duplicate'),
    (component('card', '', {'name': 'a'}) + '\n' + component('card', '', {'name': 'b'}, 'a') + '\nattach "a" "b"', 'cycle'),
    (component('heading', 'First', {'level': '1'}) + '\n' + component('heading', 'Third', {'level': '3'}), 'skip'),
    (component('link', '', {'href': '/'}), 'accessible name'),
    ('Add a form.\n' + component('input', '', {'type': 'email'}, 'form'), 'non-empty'),
    ('Add a form.\n' + component('select', 'Empty', parent='form'), 'options'),
    ('Add a form.\n' + component('input', 'Name', {'minlength': '10', 'maxlength': '2'}, 'form'), 'minlength'),
    (component('card', '', {'min-width': '100px', 'max-width': '20px'}), 'min-width'),
])
def test_accessibility_and_structure_diagnostics(source, expected):
    result = compile_body(source)
    assert not result.success
    assert any(expected in d.message for d in result.diagnostics), result.diagnostics


def test_inherited_background_and_hover_contrast():
    result = ok('Add a section. Set the section background-color to black.\nAdd a white paragraph that says "Visible" inside the section.')
    assert result.success
    result = compile_body('Add a section. Set the section background-color to black.\nAdd a black paragraph that says "Invisible" inside the section.')
    assert any('4.5:1' in d.message for d in result.diagnostics)
    result = compile_body('Create a link labelled "Visit" to "/".\nGive the link a hover color of white.')
    assert any('Hover' in d.message for d in result.diagnostics)


@pytest.mark.parametrize('source', [
    'Save form data to a database.', 'Implement authentication.', 'Create three cards for A and B.',
    'Add a numbered list of five placement preparation steps.', 'Create a bulleted list of our services.',
    'Add a dropdown for selecting a department.', 'Add a hero section with a heading, a description and a button.',
    'Each card should have a title, a short description and a button.',
])
def test_underspecified_and_unsupported_requests_do_not_invent_content(source):
    result = compile_body(source)
    assert not result.success and result.html is None
    assert 'explicit' in result.diagnostics[0].message


def test_nlp_adapter_is_reparsed_and_semantically_checked():
    converted = compile_source('Create a page titled "Test".\nAn unusual request.', nlp_converter=lambda _: component('link', 'GitHub', {'href': 'https://github.com'}))
    assert converted.success and converted.ast[1].line == 2
    assert converted.sentences[1].normalized.startswith('component')
    invalid = compile_source('Create a page titled "Test".\nAn unusual request.', nlp_converter=lambda _: component('link', 'Bad', {'href': 'javascript:alert(1)'}))
    assert not invalid.success and invalid.diagnostics[0].line == 2
    raw = compile_source('An unusual request.', nlp_converter=lambda _: '<script>alert(1)</script>')
    assert not raw.success and raw.symbols == []
    def fail(_):
        raise RuntimeError('private provider credentials')
    failure = compile_source('An unusual request.', nlp_converter=fail)
    assert failure.diagnostics[0].phase == 'normalization'
    assert 'credentials' not in failure.diagnostics[0].message


@pytest.mark.parametrize('name', ['college-event', 'personal-portfolio', 'service-landing', 'contact-page'])
def test_complete_pages_html_css_validity_and_export(name, tmp_path):
    html5lib = pytest.importorskip('html5lib')
    tinycss2 = pytest.importorskip('tinycss2')
    source = (ROOT / 'examples' / (name + '.sp')).read_text(encoding='utf-8')
    result = compile_source(source)
    assert result.success, result.diagnostics
    parser = html5lib.HTMLParser(strict=True)
    parser.parse(result.html)
    rules = tinycss2.parse_stylesheet(result.css, skip_comments=True, skip_whitespace=True)
    assert not any(rule.type == 'error' for rule in rules)
    for rule in rules:
        if rule.type == 'qualified-rule':
            values = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
            assert not any(value.type == 'error' for value in values)
    write_output(result, tmp_path, asset_root=ROOT / 'examples')
    assert (tmp_path / 'index.html').read_text(encoding='utf-8') == result.html
    again = compile_source(source)
    assert (result.html, result.css, result.debug_data()) == (again.html, again.css, again.debug_data())


def test_expanded_page_through_flask(tmp_path):
    from app import create_app
    client = create_app({'TESTING': True, 'OUTPUT_ROOT': tmp_path}).test_client()
    response = client.post('/', data={'source': (ROOT / 'examples/service-landing.sp').read_text()})
    assert response.status_code == 200 and b'Compilation successful' in response.data
    generated = list(tmp_path.glob('*/index.html'))
    assert len(generated) == 1 and '<nav ' in generated[0].read_text()


def test_instruction_words_inside_content_are_preserved():
    result = ok('Add a paragraph that says "We stay inside the house and create cards".')
    assert result.symbols[0].text == 'We stay inside the house and create cards'
    assert result.symbols[0].parent_id is None


def test_instruction_words_inside_reference_names():
    result = ok('Add a card named "come inside today".\nAdd a paragraph that says "Stay inside" inside "come inside today".\nSet "come inside today" padding to 24 pixels.\nAdd a card named "go to place".\nSet "go to place" padding to 12 pixels.')
    assert result.symbols[1].parent_id == result.symbols[0].id
    assert result.symbols[-1].properties['padding'] == '12px'


@pytest.mark.parametrize('source', [
    component('table', 'Invalid direct text'), component('ul', 'Invalid direct text'),
    'Create a table with columns for A, B and C. Add a row with "One" and "Two".',
    'Add a header. Add a footer inside the header.',
    component('label', ''),
    'Add a form.\n' + component('input', 'Agree', {'type': 'checkbox', 'maxlength': '2'}, 'form'),
])
def test_invalid_content_models(source):
    assert not compile_body(source).success


def test_image_inside_card_fit_and_position_boundaries():
    result = ok('Add a card named "profile".\nAdd a heading that says "Portrait" inside "profile".\nAdd an image called "logo.png" with the description "Portrait" inside "profile".\nPlace the image to the left of the heading.\nMake the image fit inside its card without overflowing.')
    assert 'object-fit: contain' in result.css
    assert result.page_tree.children[0].children[0].direction == 'row'
    invalid = compile_body('Add a card.\nAdd a heading that says "Inside" inside the card.\nAdd a button that says "Outside".\nPut it below the heading.')
    assert any('share a parent' in d.message for d in invalid.diagnostics)


def test_explicit_label_and_aside():
    result = ok('Add a main.\nAdd an aside inside the main.\nAdd a form inside the aside.\nAdd a text field labelled "Full name".\nSet it name to "fullname".\nAdd a label that says "Legal name".\nSet the label for to "fullname".')
    assert '<aside ' in result.html
    assert len(Document(result.html).tags('label')) == 2


@pytest.mark.parametrize('source', [r'Create a link labelled "bad\q" to "/".', r'Add an image called "bad\q.png" with the description "Photo".', r'Create three cards for "bad\q", "B" and "C".'])
def test_bad_extended_literals_are_diagnostics_not_exceptions(source):
    result = compile_body(source)
    assert not result.success and result.diagnostics[0].phase == 'syntax'


def test_original_single_quotes_and_periods_are_retained():
    source = "Create a link labelled 'Visit. GitHub' to 'https://github.com'."
    result = ok(source)
    assert result.sentences[1].original == source
    assert result.symbols[0].text == 'Visit. GitHub'


def test_font_size_aliases_honor_last_assignment():
    result = ok('Add a heading that says "Title". Set it font-size to 24 pixels. Make it small.')
    assert 'font-size: 0.875rem' in result.css and 'font-size: 24px' not in result.css
    reverse = ok('Add a small heading that says "Title". Set it font-size to 24 pixels.')
    assert 'font-size: 24px' in reverse.css and 'font-size: 0.875rem' not in reverse.css


def test_actual_button_text_color_and_heading_level_paraphrases():
    result = ok('Add a blue button that says "Continue". Give the button a text color of white.')
    assert 'background-color: #2b6cb0' in result.css and 'color: #ffffff' in result.css
    first = ok('Add a level 2 heading that says "Title".')
    second = ok('Add a heading that says "Title" at level 2.')
    assert (first.html, first.css) == (second.html, second.css)
