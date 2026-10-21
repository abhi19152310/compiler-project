from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from text2web import compile_source
from text2web.codegen import write_output
from text2web.normalizer import normalize
from text2web.parser import PARSER

ROOT = Path(__file__).resolve().parents[1]
DEMO = (ROOT / "examples" / "fest.sp").read_text(encoding="utf-8")


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_demo_generates_actual_html_and_css(tmp_path):
    result = compile_source(DEMO)
    assert result.success
    write_output(result, tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    css = (tmp_path / "style.css").read_text(encoding="utf-8")
    document = Document(html)
    assert "Techno Fest" in document.text
    assert "Techno 2026" in document.text
    assert "Welcome to our college fest" in document.text
    assert "Register" in document.text
    assert ("button", {"id": "element3", "type": "button"}) in document.tags
    assert ("link", {"rel": "stylesheet", "href": "style.css"}) in document.tags
    assert "#element3 { background-color: #2b6cb0; color: #ffffff; font-weight: 700; }" in css


def test_normalization_preserves_quotes_and_source_lines():
    source = '\n Please INSERT a big BLUE button that says "Create  THE Page. Please!".\n'
    sentence = normalize(source)[0]
    assert sentence.line == 2
    assert sentence.normalized == 'please add a big blue button that says "Create  THE Page. Please!".'


def test_normalization_splits_sentences_outside_quotes_and_keeps_source_line():
    sentences = normalize(
        'Create a page titled "Page. One". Add a heading that says "Heading".\n'
        'Please move it to the left of the heading.'
    )
    assert [sentence.line for sentence in sentences] == [1, 1, 2]
    assert sentences[0].normalized == 'add a page titled "Page. One".'
    assert sentences[1].normalized == 'add a heading that says "Heading".'
    assert sentences[2].normalized == 'please put it to the left of the heading.'


@pytest.mark.parametrize("verb", ["Add", "Create", "INSERT"])
def test_synonyms_and_optional_words(verb):
    result = compile_source(f'create page titled "Demo"\nplease {verb} the paragraph says "Text"')
    assert result.success
    assert result.symbols[0].text == "Text"


@pytest.mark.parametrize("reference", ["it", "this"])
def test_reference_resolves_to_last_introduced_element(reference):
    result = compile_source(
        'Create a page titled "Demo".\nAdd a heading that says "Heading".\n'
        f'Add a button that says "Button".\nMake {reference} bold.\nMake it bold.'
    )
    assert result.success
    assert result.symbols[0].properties == {}
    assert result.symbols[1].properties == {"font-weight": "bold"}
    assert result.ast[-1].resolved_id == result.ast[-2].resolved_id == "element2"


def test_unresolved_reference_is_error():
    result = compile_source('Create a page titled "Demo".\n\nMake it bold.')
    assert not result.success
    assert result.diagnostics[0].line == 3
    assert result.diagnostics[0].phase == "reference"
    assert result.html is None and result.css is None


@pytest.mark.parametrize("instruction", [
    'Add a heading that says Hello.',
    'Add a purple button that says "Go".',
    'Add a blue big button that says "Go".',
    'Make it italic.',
    'Add an image "logo.png".',
    'Add a heading that says "Unclosed.',
    'Add a heading that says "One"..',
])
def test_invalid_syntax_reports_original_line_and_blocks_output(instruction, tmp_path):
    result = compile_source('Create a page titled "Demo".\n\n' + instruction)
    assert not result.success
    assert result.diagnostics[0].line == 3
    assert result.diagnostics[0].phase == "syntax"
    assert result.html is None and result.css is None
    with pytest.raises(ValueError):
        write_output(result, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()


def test_independent_syntax_errors_are_collected_without_resolving_partial_ast():
    result = compile_source('Create a page titled "Demo".\nBad sentence.\nMake it bold.\nMore bad text.')
    assert [e.line for e in result.diagnostics] == [2, 4]
    assert result.symbols == []
    assert result.ast[-1].resolved_id is None


@pytest.mark.parametrize("source", [
    "", " \n\t", 'Add a heading that says "No page".',
    'Create a page titled "One".\nCreate a page titled "Two".',
])
def test_document_structure_errors(source):
    result = compile_source(source)
    assert not result.success
    assert result.diagnostics


def test_text_is_escaped_in_html_and_preserved_in_ast():
    text = '<script>alert("x")</script> & Café नमस्ते.  Two spaces'
    result = compile_source(
        f'Create a page titled {json.dumps(text)}.\n'
        f'Add a paragraph that says {json.dumps(text)}.'
    )
    assert result.success
    assert result.ast[1].text == text
    assert result.symbols[0].text == text
    document = Document(result.html)
    assert "script" not in [tag for tag, _ in document.tags]
    assert text in document.text
    assert "&lt;script&gt;" in result.html


@pytest.mark.parametrize("text", [r'"bad\q"', r'"bad\ud800"'])
def test_invalid_string_escapes_report_error(text):
    result = compile_source(f'Create a page titled {text}.')
    assert not result.success
    assert result.diagnostics[0].phase == "syntax"


@pytest.mark.parametrize("size,expected", [("small", "0.875rem"), ("medium", "1.125rem"), ("big", "2.5rem")])
def test_sizes_and_text_color(size, expected):
    result = compile_source(f'Create a page titled "Demo".\nAdd a {size} red paragraph that says "Text".')
    assert result.success
    assert f"font-size: {expected}" in result.css
    assert "color: #b91c1c" in result.css


def test_real_lalr_parser_and_visible_tokens():
    assert PARSER.options.parser == "lalr"
    result = compile_source(DEMO)
    assert {t["type"] for t in result.tokens} >= {"ADD", "STRING", "ELEMENT", "COLOR", "SIZE", "BOLD"}
    assert [t for t in result.tokens if t["type"] == "BOLD"][0]["line"] == 5


def test_deterministic_compilation():
    first, second = compile_source(DEMO), compile_source(DEMO)
    assert first.success and second.success
    assert (first.html, first.css, first.debug_data()) == (second.html, second.css, second.debug_data())


def test_existing_outputs_are_preserved_unless_explicitly_overwritten(tmp_path):
    existing = tmp_path / "index.html"
    existing.write_text("original", encoding="utf-8")
    result = compile_source(DEMO)
    with pytest.raises(FileExistsError):
        write_output(result, tmp_path)
    assert existing.read_text() == "original"
    assert not (tmp_path / "style.css").exists()
    write_output(result, tmp_path, overwrite=True)
    assert existing.read_text(encoding="utf-8") == result.html


def test_cli_success_failure_and_existing_output_preservation(tmp_path):
    command = [sys.executable, "-m", "text2web"]
    valid = subprocess.run(command + [str(ROOT / "examples/fest.sp"), "--output", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    original = (tmp_path / "index.html").read_bytes()
    invalid = subprocess.run(command + [str(ROOT / "examples/invalid.sp"), "--output", str(tmp_path), "--force"], cwd=ROOT, capture_output=True, text=True)
    assert invalid.returncode == 1
    assert "Line 3 [syntax]" in invalid.stderr
    assert (tmp_path / "index.html").read_bytes() == original
