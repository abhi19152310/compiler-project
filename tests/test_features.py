from pathlib import Path

from text2web import compile_source
from text2web.codegen import write_output


def test_image_description_and_position_generate_accessible_row():
    result = compile_source(
        'Create a page titled "Fest".\n'
        'Add a heading that says "Stage".\n'
        'Add an image "stage.png" described as "Main stage".\n'
        'Put it to the left of the heading.'
    )
    assert result.success
    assert result.ast[-1].resolved_id == "element2"
    assert result.ast[-1].target_id == "element1"
    assert result.page_tree.children[0].direction == "row"
    assert [node.element_id for node in result.page_tree.children[0].children] == ["element2", "element1"]
    assert '<img id="element2" src="stage.png" alt="Main stage">' in result.html
    assert ".row { display: flex; flex-direction: row;" in result.css


def test_opposite_positions_report_both_source_lines_and_prevent_output():
    result = compile_source(
        'Create a page titled "Fest".\n'
        'Add a heading that says "Stage".\n'
        'Add an image "stage.png" described as "Main stage".\n'
        'Put it to the left of the heading.\n'
        'Put it to the right of the heading.'
    )
    assert not result.success
    assert result.html is None
    assert result.diagnostics[-1].phase == "layout"
    assert result.diagnostics[-1].line == 5
    assert "line 4" in result.diagnostics[-1].message


def test_above_and_below_constraints_make_a_column():
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add a heading that says "Top".\n'
        'Add a paragraph that says "Bottom".\n'
        'Put it above the heading.'
    )
    assert result.success
    assert result.page_tree.children[0].direction == "column"
    assert [node.element_id for node in result.page_tree.children[0].children] == ["element2", "element1"]
    assert ".column { display: flex; flex-direction: column;" in result.css


def test_row_and_column_constraints_create_nested_page_tree():
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add a heading that says "A".\n'
        'Add a paragraph that says "B".\n'
        'Add a button that says "C".\n'
        'Put it to the right of the heading.\n'
        'Put it below the paragraph.'
    )
    assert result.success
    row = result.page_tree.children[0]
    assert row.direction == "row"
    assert [node.element_id for node in row.children] == ["element1", None]
    assert row.children[1].direction == "column"
    assert [node.element_id for node in row.children[1].children] == ["element2", "element3"]
    assert '<div class="row">\n      <h1' in result.html


def test_missing_image_description_and_unsafe_image_url_are_errors():
    missing = compile_source(
        'Create a page titled "Page".\nAdd an image "stage.png" described as "".'
    )
    assert not missing.success
    assert any(item.phase == "accessibility" and "description" in item.message for item in missing.diagnostics)

    unsafe = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "javascript:alert(1)" described as "Stage".'
    )
    assert not unsafe.success
    assert any(item.phase == "semantic" and "HTTP(S)" in item.message for item in unsafe.diagnostics)


def test_contrast_and_element_type_errors_block_compilation():
    contrast = compile_source(
        'Create a page titled "Page".\n'
        'Add a white heading that says "Invisible".'
    )
    assert not contrast.success
    assert any(item.phase == "accessibility" and "4.5:1" in item.message for item in contrast.diagnostics)

    invalid_font = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "stage.png" described as "Stage".\n'
        'Make it Arial.'
    )
    assert not invalid_font.success
    assert invalid_font.diagnostics[-1].phase == "type"


def test_identical_styles_are_merged_and_later_values_win():
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add a red heading that says "One".\n'
        'Make it bold.\n'
        'Add a red paragraph that says "Two".\n'
        'Make it bold.'
    )
    assert result.success
    assert result.css.count("#element1, #element2 {") == 1
    assert result.css.count("font-weight: 700") == 1


def test_image_attributes_are_escaped():
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "stage\\\"><script>.png" described as "Main & stage".'
    )
    assert result.success
    assert 'src="stage&quot;&gt;&lt;script&gt;.png"' in result.html
    assert 'alt="Main &amp; stage"' in result.html


def test_layout_cycles_are_reported_for_multiple_independent_constraints():
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add a heading that says "One".\n'
        'Add a paragraph that says "Two".\n'
        'Add a button that says "Three".\n'
        'Put it to the left of the heading.\n'
        'Put it to the left of the paragraph.\n'
        'Put it to the right of the heading.'
    )
    assert not result.success
    assert any(item.phase == "layout" and item.line == 7 for item in result.diagnostics)


def test_multiple_instructions_on_one_line_keep_original_line_numbers():
    result = compile_source(
        'Create a page titled "Page". Add a heading that says "Heading". Make it bold.'
    )
    assert result.success
    assert [sentence.line for sentence in result.sentences] == [1, 1, 1]
    assert [statement.line for statement in result.ast] == [1, 1, 1]
    assert result.symbols[0].properties["font-weight"] == "bold"


def test_syntax_error_recovery_synchronizes_at_full_stops():
    result = compile_source(
        'Create a page titled "Page". Bad instruction. Add a heading that says "Heading".'
    )
    assert not result.success
    assert [(error.phase, error.line) for error in result.diagnostics] == [("syntax", 1)]
    assert [statement.kind for statement in result.ast] == ["page", "add"]


def test_portfolio_example_compiles():
    example = Path(__file__).resolve().parents[1] / "examples" / "portfolio.sp"
    result = compile_source(example.read_text(encoding="utf-8"))
    assert result.success
    assert "Alex Morgan" in result.html
    assert "flex-direction: column" in result.css
    assert "font-weight: 700" in result.css


def test_cli_style_copy_and_uploaded_assets(tmp_path):
    result = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "assets/stage.png" described as "Main stage".'
    )
    assert result.success

    with_assets = tmp_path / "source"
    output = tmp_path / "output"
    with_assets.mkdir()
    (with_assets / "assets").mkdir()
    image = b"\x89PNG\r\n\x1a\nexample"
    (with_assets / "assets" / "stage.png").write_bytes(image)
    write_output(result, output, asset_root=with_assets)
    assert (output / "assets" / "stage.png").read_bytes() == image

    upload_output = tmp_path / "upload-output"
    write_output(result, upload_output, assets={"assets/stage.png": image})
    assert (upload_output / "assets" / "stage.png").read_bytes() == image


def test_local_images_require_a_safe_existing_asset(tmp_path):
    unsafe = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "../stage.png" described as "Main stage".'
    )
    assert not unsafe.success
    assert any(item.phase == "semantic" for item in unsafe.diagnostics)

    missing = compile_source(
        'Create a page titled "Page".\n'
        'Add an image "stage.png" described as "Main stage".'
    )
    output = tmp_path / "must-not-exist"
    try:
        write_output(missing, output)
    except FileNotFoundError as error:
        assert "stage.png" in str(error)
        assert not output.exists()
    else:
        raise AssertionError("Writing a local image without its asset must fail.")
