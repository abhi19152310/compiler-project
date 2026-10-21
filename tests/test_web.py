from io import BytesIO
from pathlib import Path
import re

import pytest

from app import create_app

ROOT = Path(__file__).resolve().parents[1]
DEMO = (ROOT / "examples/fest.sp").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "OUTPUT_ROOT": tmp_path / "web"})
    return app.test_client()


def test_editor_is_available(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Compile Webpage" in response.data
    assert b"Supported sentence guide" in response.data
    assert b"Page Tree (IR)" in response.data
    assert b"4.5:1 contrast minimum" in response.data


def test_compile_preview_and_download_are_real_files(client, tmp_path):
    response = client.post("/", data={"source": DEMO})
    assert response.status_code == 200
    assert b"Compilation successful" in response.data
    assert b"Symbol Table" in response.data and b"Tokens" in response.data
    preview_url = re.search(rb'sandbox src="([^"]+)"', response.data)[1].decode()
    preview = client.get(preview_url)
    assert preview.status_code == 200
    assert b"Techno 2026" in preview.data
    css = client.get(preview_url.replace("index.html", "style.css"))
    assert css.status_code == 200
    assert b"font-weight: 700" in css.data
    download = client.get(preview_url + "?download=1")
    assert "attachment" in download.headers["Content-Disposition"]
    css_download = client.get(preview_url.replace("index.html", "style.css") + "?download=1")
    assert "attachment" in css_download.headers["Content-Disposition"]
    assert css_download.data == css.data
    saved = list((tmp_path / "web").glob("*/index.html"))
    assert len(saved) == 1 and saved[0].read_bytes() == preview.data


def test_uploaded_image_is_saved_and_served_with_the_compiled_page(client):
    source = (
        'Create a page titled "Page".\n'
        'Add an image "stage.png" described as "Main stage".'
    )
    response = client.post("/", data={
        "source": source,
        "assets": (BytesIO(b"\x89PNG\r\n\x1a\nimage"), "stage.png", "image/png"),
    })
    match = re.search(rb'sandbox src="([^"]+)"', response.data)
    assert match
    preview_url = match[1].decode()
    assert b'<img id="element1" src="stage.png" alt="Main stage">' in client.get(preview_url).data
    image = client.get(preview_url.replace("index.html", "stage.png"))
    assert image.status_code == 200
    assert image.data == b"\x89PNG\r\n\x1a\nimage"


def test_web_image_upload_errors_are_reported(client):
    source = (
        'Create a page titled "Page".\n'
        'Add an image "stage.png" described as "Main stage".'
    )
    missing = client.post("/", data={"source": source})
    assert b"Upload the image file(s)" in missing.data
    assert b"<iframe" not in missing.data

    invalid = client.post("/", data={
        "source": source,
        "assets": (BytesIO(b"not an image"), "stage.png", "image/png"),
    })
    assert b"is not a supported PNG" in invalid.data
    assert b"<iframe" not in invalid.data


def test_editor_keeps_the_original_source_size_limit(client):
    response = client.post("/", data={"source": "x" * (128 * 1024 + 1)})
    assert b"Source instructions cannot exceed 128 KB" in response.data
    assert b"<iframe" not in response.data


def test_failed_compile_has_no_preview_or_written_files(client, tmp_path):
    response = client.post("/", data={"source": 'Create a page titled "Bad".\nMake it bold.'})
    assert response.status_code == 200
    assert b"Line 2:" in response.data
    assert b"<iframe" not in response.data
    assert not (tmp_path / "web").exists()


def test_failed_attempt_does_not_display_previous_success(client, tmp_path):
    client.post("/", data={"source": DEMO})
    response = client.post("/", data={"source": "Invalid instruction."})
    assert b"<iframe" not in response.data
    assert len(list((tmp_path / "web").glob("*/index.html"))) == 1


def test_source_cannot_break_out_of_editor(client):
    response = client.post("/", data={"source": '</textarea><script>alert(1)</script>'})
    assert b"<script>" not in response.data
    assert b"&lt;/textarea&gt;" in response.data


@pytest.mark.parametrize("path", ["/build/nope/index.html", "/build/" + "a" * 32 + "/app.py", "/build/" + "a" * 32 + "/index.html"])
def test_output_route_rejects_invalid_or_missing_files(client, path):
    assert client.get(path).status_code == 404


def test_file_write_failure_is_reported(client, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("test")
    monkeypatch.setattr("app.write_output", fail)
    response = client.post("/", data={"source": DEMO})
    assert b"output files could not be saved" in response.data
    assert b"<iframe" not in response.data


def test_inspector_shows_real_custom_input_and_resolved_symbols(client):
    source = 'Create a page titled "Custom".\nInsert a red paragraph that says "Actual input".\nMake this bold.'
    response = client.post("/", data={"source": source})
    html = response.get_data(as_text=True)
    assert 'add a red paragraph that says' in html
    assert 'Actual input' in html
    assert 'element1' in html
    assert 'font-weight' in html and 'bold' in html
    assert 'element3' not in html
    assert 'id="pane-ast"' in html and 'id="pane-symbol_table"' in html
    sample = re.search(r'<template id="sample-source">(.*?)</template>', html, re.S)[1]
    assert 'Techno Fest' in sample
    assert 'Actual input' not in sample


def test_initial_inspector_does_not_fabricate_results(client):
    html = client.get("/").get_data(as_text=True)
    assert 'Ready to compile' in html
    assert 'Compile to view introduced elements' in html
    assert '<iframe' not in html
    assert 'element1' not in html
    assert 'id="download-html"' not in html
