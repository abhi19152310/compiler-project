"""Checks for accessible names, safe image sources, and text contrast."""

from .assets import local_asset_path
from .properties import COLORS, CONTAINERS, color, contrast as _contrast, readable_foreground
from .model import CompilationResult, Diagnostic, Element

WHITE = "#ffffff"


def _check_image(element: Element, result: CompilationResult) -> None:
    if not element.properties.get("alt", element.text).strip() and element.properties.get("decorative") != "true":
        result.diagnostics.append(Diagnostic(
            "accessibility", element.line, "Images need a non-empty description for alternative text.",
        ))
    source = element.properties.get("src", "")
    try:
        local_asset_path(source)
    except ValueError:
        result.diagnostics.append(Diagnostic(
            "semantic", element.line,
            "Image sources must be a safe relative path or an HTTP(S) URL without credentials.",
        ))


def check_accessibility(result: CompilationResult) -> None:
    by_id = {e.id: e for e in result.symbols}
    previous_level = 0
    ordered = []
    def walk(nodes):
        for node in nodes:
            if node.element_id:
                ordered.append(by_id[node.element_id])
            walk(node.children)
    if result.page_tree:
        walk(result.page_tree.children)
    else:
        ordered = result.symbols
    for element in ordered:
        if element.type == "image":
            _check_image(element, result)
            continue
        children = [e for e in result.symbols if e.parent_id == element.id]
        if element.type == "heading":
            level = int(element.properties.get("level", "1"))
            if previous_level and level > previous_level + 1:
                result.diagnostics.append(Diagnostic("accessibility", element.line, 'Heading levels must not skip a level.'))
            previous_level = level
        named_by_child = element.type == "link" and any(e.type == "image" and e.properties.get("decorative") != "true" and e.properties.get("alt", e.text).strip() or e.type == "paragraph" and e.text.strip() for e in children)
        if element.type in {"button", "submit"} and not element.text.strip():
            result.diagnostics.append(Diagnostic(
                "accessibility", element.line, "Buttons need visible text to provide an accessible name.",
            ))
        elif element.type in {"label", "th"} and not element.text.strip():
            result.diagnostics.append(Diagnostic("accessibility", element.line, 'Labels and table headers need non-empty text.'))
        elif element.type == "link" and not element.text.strip() and not named_by_child and not element.properties.get("aria-label"):
            result.diagnostics.append(Diagnostic("accessibility", element.line, 'Links need a meaningful accessible name.'))
        elif element.type not in CONTAINERS and not element.text.strip():
            result.diagnostics.append(Diagnostic(
                "accessibility", element.line,
                f"{element.type.capitalize()} elements need non-empty text.",
            ))
        if element.type in {"select"} and not element.text.strip():
            result.diagnostics.append(Diagnostic("accessibility", element.line, 'Form fields need a non-empty label.'))
        if not element.text.strip():
            continue
        ancestry = []
        ancestor = element
        while ancestor:
            ancestry.append(ancestor.properties)
            ancestor = by_id.get(ancestor.parent_id)
        ancestry.append(result.page_properties)
        foreground = color(next((p.get("text-color", p.get("color")) for p in ancestry if "color" in p or "text-color" in p), "blue" if element.type == "link" else "black"))
        background = color(next((p["background-color"] for p in ancestry if "background-color" in p), "white"))
        color_name = element.properties.get("color", foreground)
        if element.type in {"button", "submit"} and "color" in element.properties:
            background = color(element.properties.get("background-color", color_name))
            foreground = color(element.properties.get("text-color", readable_foreground(background)))
        # Background images cannot be evaluated by a solid-color contrast check.
        if any("background-image" in p for p in ancestry):
            continue
        # Low contrast is reported as a warning: the page is still generated.
        ratio = _contrast(foreground, background)
        if ratio < 4.5:
            result.warnings.append(Diagnostic(
                "contrast", element.line,
                f'The {color_name} color on this {element.type} has {ratio:.1f}:1 text contrast, below the recommended '
                f'4.5:1 minimum; {readable_foreground(background)} text would be readable.',
            ))
        hover_foreground = color(element.properties.get("hover-color", foreground))
        hover_background = color(element.properties.get("hover-background-color", background))
        if _contrast(hover_foreground, hover_background) < 4.5 and any(k.startswith("hover-") for k in element.properties):
            result.warnings.append(Diagnostic("contrast", element.line, 'Hover colors are below the recommended 4.5:1 text contrast minimum.'))
