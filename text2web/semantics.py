"""Symbol resolution, typed properties and parent/child HTML content models."""

import re

from .model import CompilationResult, Diagnostic, Element
from .properties import CONTAINERS, TYPES, validate_property


def lookup(result, reference, line, *, plural=False):
    reference = reference or "it"
    if reference.startswith("ordinal:") and not re.fullmatch(r'ordinal:[a-z]+:(?:[1-9]\d*|-1)', reference) or reference.startswith("position:") and not re.fullmatch(r'position:[a-z]+:(?:left|right|above|below)', reference):
        result.diagnostics.append(Diagnostic("reference", line, 'Invalid component selector. Please use a name, ordinal or direction.'))
        return []
    if reference == "safe:it":
        matches = [e for e in result.symbols if e.id == result.focus_id]
        if not matches:
            result.diagnostics.append(Diagnostic("clarification", line, 'Which component do you mean by "it"? Name it or describe its type and position.'))
            return []
    elif reference.startswith("unique:"):
        kind = reference[7:]
        matches = [e for e in result.symbols if e.type == kind]
        if len(matches) > 1:
            result.diagnostics.append(Diagnostic("clarification", line, f'There are {len(matches)} {kind} components. Which one should change? Use its name, or say first/second/last.'))
            return []
    elif reference.startswith("ordinal:"):
        _, kind, index = reference.split(":", 2)
        choices = [e for e in result.symbols if e.type == kind]
        number = int(index)
        matches = choices[number - 1:number] if number > 0 else choices[-1:]
    elif reference.startswith("position:"):
        _, kind, direction = reference.split(":", 2)
        candidates = {e.id for e in result.symbols if e.type == kind}
        ids = {s.resolved_id for s in result.ast if s.kind == "position" and s.properties.get("position") == direction}
        opposites = {"left": "right", "right": "left", "above": "below", "below": "above"}
        ids.update(s.target_id for s in result.ast if s.kind == "position" and s.properties.get("position") == opposites[direction])
        matches = [e for e in result.symbols if e.id in candidates & ids]
        if len(matches) > 1:
            result.diagnostics.append(Diagnostic("clarification", line, f'More than one {kind} is {direction}. Please specify a name.'))
            return []
    elif reference in {"it", "this"}:
        matches = result.symbols[-1:]
    elif reference == "fields":
        matches = [e for e in result.symbols if e.type in {"input", "textarea", "select"}][-1:]
    elif reference.startswith("all:") and plural:
        matches = [e for e in result.symbols if e.type == reference[4:]]
    else:
        exact = reference.removeprefix('named:')
        named = [e for e in result.symbols if exact in {e.id, e.name, e.properties.get("id")}]
        if not named:
            named = [e for e in result.symbols if e.text == exact]
        if len(named) > 1:
            result.diagnostics.append(Diagnostic("reference", line, f'Ambiguous reference "{reference}"; give elements unique names.'))
            return []
        matches = named or [e for e in result.symbols if e.type == reference][-1:]
    if not matches:
        result.diagnostics.append(Diagnostic("reference", line, f'Cannot resolve "{reference}": add and name the element before referencing it.'))
    return matches


def resolve(result: CompilationResult, *, title="", statements=None, finalize=True) -> str:
    page_seen = bool(title)

    def error(phase, line, message):
        result.diagnostics.append(Diagnostic(phase, line, message))

    def attach(element, parent, line):
        if parent.type not in CONTAINERS:
            error("type", line, f'{parent.type} cannot contain child elements.')
            return
        ancestor = parent
        by_id = {e.id: e for e in result.symbols}
        while ancestor:
            if ancestor.id == element.id:
                error("semantic", line, 'Containment would create a parent-child cycle.')
                return
            ancestor = by_id.get(ancestor.parent_id)
        element.parent_id = parent.id

    for statement in result.ast if statements is None else statements:
        if statement.kind == "page":
            if page_seen:
                error("semantic", statement.line, "Only one page title is allowed.")
            elif not (statement.text or "").strip():
                error("semantic", statement.line, "Page title cannot be empty.")
            else:
                title, page_seen = statement.text or "", True
            continue
        if not page_seen:
            error("semantic", statement.line, 'Start with: Create a page titled "My Page".')
        if statement.kind == "add":
            kind = statement.element_type or ""
            if kind not in TYPES:
                error("type", statement.line, f'Unsupported component "{kind}".')
                continue
            parents = lookup(result, statement.parent_reference, statement.line, plural=True) if statement.parent_reference else []
            targets = []
            for parent in parents or [None]:
                target = Element(f"element{len(result.symbols) + 1}", kind, statement.text or "",
                                 {}, statement.line, extended=statement.extended)
                result.symbols.append(target)
                statement.resolved_id = target.id
                targets.append(target)
                if parent:
                    attach(target, parent, statement.line)
        elif statement.kind == "format" and statement.reference == "page":
            for key, value in statement.properties.items():
                message = validate_property("container", key, value)
                if message or key not in {"color", "text-color", "background-color", "background-image", "font-family", "font-size", "line-height", "responsive"}:
                    error("type", statement.line, message or f'Unsupported page property: {key}.')
                else:
                    result.page_properties[key] = value
            continue
        else:
            targets = lookup(result, statement.reference, statement.line, plural=statement.kind in {"format", "attach"})
            if not targets:
                continue
            statement.resolved_id = targets[-1].id
            if statement.kind == "wrap":
                target = targets[0]
                message = validate_property("link", "href", statement.properties["href"])
                if message or target.type not in {"image", "link"}:
                    error("type", statement.line, message or 'Only images can be wrapped as logo links.')
                    continue
                if target.type == "link":
                    target.properties["href"] = statement.properties["href"]
                    continue
                wrapper = Element(f"element{len(result.symbols) + 1}", "link", "", dict(statement.properties),
                                  statement.line, parent_id=target.parent_id, name=target.name, extended=True)
                if target.name:
                    wrapper.properties["name"] = target.properties.pop("name")
                    target.name = None
                # Layout properties belong to the outer anchor once it is a flex item.
                for key in ("order", "margin-left", "margin-right", "align-self"):
                    if key in target.properties:
                        wrapper.properties[key] = target.properties.pop(key)
                result.symbols.append(wrapper)
                target.parent_id = wrapper.id
                statement.target_id = wrapper.id
                for previous in result.ast:
                    if previous.kind == "position":
                        if previous.resolved_id == target.id:
                            previous.resolved_id = wrapper.id
                        if previous.target_id == target.id:
                            previous.target_id = wrapper.id
                continue
            if statement.kind == "attach":
                parents = lookup(result, statement.parent_reference, statement.line)
                if parents:
                    for target in targets:
                        attach(target, parents[0], statement.line)
                continue
            if statement.kind == "position":
                other = lookup(result, statement.target_type, statement.line)
                if other:
                    statement.target_id = other[0].id
                continue
        for target in targets:
            for key, value in statement.properties.items():
                message = validate_property(target.type, key, value)
                if message:
                    error("type" if key != "src" else "semantic", statement.line, message)
                else:
                    if key in {"size", "font-size"}:
                        target.properties.pop("font-size" if key == "size" else "size", None)
                    if key in {"color", "text-color"} and target.type not in {"button", "submit"}:
                        target.properties.pop("color" if key == "text-color" else "text-color", None)
                    target.properties[key] = value
                    if key == "name":
                        target.name = value
            target.extended = target.extended or statement.extended
    if finalize:
        validate_relationships(result)
    return title


def validate_relationships(result):
    by_id = {e.id: e for e in result.symbols}
    seen_ids, seen_names = set(), set()
    mains = 0
    for element in result.symbols:
        def error(message):
            result.diagnostics.append(Diagnostic("semantic", element.line, message))
        props = element.properties
        identifier = props.get("id", element.id)
        if identifier in seen_ids:
            error(f'Duplicate HTML id "{identifier}".')
        seen_ids.add(identifier)
        if element.name:
            if element.name in seen_names and not (element.type == "input" and props.get("type") == "radio"):
                error(f'Duplicate element name "{element.name}"; use unique names.')
            seen_names.add(element.name)
        parent = by_id.get(element.parent_id)
        required_parents = {"li": {"ul", "ol"}, "tr": {"table"}, "td": {"tr"}, "th": {"tr"}, "option": {"select"}}
        if element.type in required_parents and (not parent or parent.type not in required_parents[element.type]):
            error(f'{element.type} requires a parent of type {", ".join(sorted(required_parents[element.type]))}.')
        allowed_children = {"ul": {"li"}, "ol": {"li"}, "table": {"tr"}, "tr": {"th", "td"}, "select": {"option"}}
        if parent and parent.type in allowed_children and element.type not in allowed_children[parent.type]:
            error(f'{parent.type} cannot contain {element.type}.')
        if element.type in {"ul", "ol", "table", "tr"} and element.text.strip():
            error(f'{element.type} content must use child items or cells, not direct text.')
        ancestors = []
        ancestor = parent
        while ancestor:
            ancestors.append(ancestor.type)
            if len(ancestors) >= 64:
                error('Components can be nested at most 63 levels deep.')
                break
            ancestor = by_id.get(ancestor.parent_id)
        if "link" in ancestors and element.type not in {"image", "paragraph"}:
            error('Links may contain only an image or paragraph in this DSL; nested interactive elements are invalid.')
        if "label" in ancestors:
            error('Labels use a for reference; put controls alongside the label.')
        if element.type == "form" and "form" in ancestors:
            error('Forms cannot be nested.')
        if element.type in {"header", "footer"} and any(a in {"header", "footer"} for a in ancestors):
            error('Headers and footers cannot be nested inside headers or footers.')
        if element.type in {"input", "textarea", "select", "submit"} and "form" not in ancestors:
            error(f'{element.type} must be placed inside a form.')
        if element.type == "main":
            mains += 1
            if any(a in {"main", "header", "footer", "aside", "nav", "form", "link"} for a in ancestors):
                error('Main content cannot be nested in another main or a header, footer, aside, nav, form or link.')
        if element.type == "link" and not props.get("href"):
            error('Links need a meaningful href destination.')
        if element.type == "image" and not props.get("src"):
            error('Images need a source URL or local asset path.')
        if "minlength" in props and "maxlength" in props and int(props["minlength"]) > int(props["maxlength"]):
            error('minlength cannot exceed maxlength.')
        for axis in ("width", "height"):
            low, high = props.get("min-" + axis, ""), props.get("max-" + axis, "")
            if low.endswith("px") and high.endswith("px") and float(low[:-2]) > float(high[:-2]):
                error(f'min-{axis} cannot exceed max-{axis}.')
        if element.type == "input" and props.get("type") == "radio" and not props.get("name"):
            error('Radio inputs need a shared name to define their group.')
        if element.type == "select" and not any(e.parent_id == element.id for e in result.symbols):
            error('Dropdowns need explicit options.')
        if element.type == "input" and props.get("type") in {"checkbox", "radio"} and any(k in props for k in {"minlength", "maxlength", "placeholder"}):
            error('Checkboxes and radios cannot have text length constraints or placeholders.')
        if element.type == "table":
            rows = [e for e in result.symbols if e.parent_id == element.id]
            counts = {sum(e.parent_id == row.id for e in result.symbols) for row in rows}
            if len(counts) > 1:
                error('Table rows must have the same number of cells as the column headers.')
    if mains > 1:
        result.diagnostics.append(Diagnostic("semantic", 1, 'Only one main element is allowed.'))
    for element in result.symbols:
        href = element.properties.get("href", "")
        if href.startswith("#") and href[1:] not in seen_ids:
            result.diagnostics.append(Diagnostic("reference", element.line, f'No element has the fragment ID "{href[1:]}".'))
        if element.type == "label":
            matches = lookup(result, element.properties.get("for", ""), element.line) if element.properties.get("for") else []
            if not matches or matches[0].type not in {"input", "textarea", "select"}:
                result.diagnostics.append(Diagnostic("reference", element.line, 'Labels need a for reference to an input, textarea or select.'))
            else:
                element.properties["for"] = matches[0].properties.get("id", matches[0].id)
