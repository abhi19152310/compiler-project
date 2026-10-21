"""Transactional English edits to persistent compiler symbols and page-tree IR."""

from copy import deepcopy
import re
from time import perf_counter

from .accessibility import check_accessibility
from .codegen import generate
from .intents import IntentError, safe_target
from .layout import build_page_tree, optimize_page_tree
from .model import CompilationResult, Diagnostic, Sentence
from .normalizer import normalize
from .offline import target as english_target
from .parser import parse_sentence
from .properties import COLORS, TYPES, color, readable_foreground
from .semantics import lookup, resolve, validate_relationships


def segment(source):
    """Split sentence/clause boundaries only outside quoted text, preserving lines."""
    quoted, escaped, start = None, False, 0
    boundaries = []
    for i, char in enumerate(source):
        if quoted and escaped:
            escaped = False
        elif quoted and char == '\\':
            escaped = True
        elif quoted and char == quoted:
            quoted = None
        elif not quoted and (char == '"' or char == "'" and (i == 0 or not source[i - 1].isalnum())):
            quoted = char
        elif not quoted:
            if char in '\n;' or char in '.!?' and (i + 1 == len(source) or source[i + 1].isspace()):
                boundaries.append((i, i + 1))
            elif source[i:i + 1].isspace():
                conjunction = re.match(r'\s+(?:(?:and\s+)?then|and)\s+(?=(?:add|create|build|insert|make|put|place|move|change|set|show|give|display)\b)', source[i:], re.I)
                if conjunction:
                    boundaries.append((i, i + conjunction.end()))
    for end, after in sorted(set(boundaries)):
        if end < start:
            continue
        content = source[start:end].strip().rstrip(',')
        if content:
            leading = len(source[start:end]) - len(source[start:end].lstrip())
            yield source.count('\n', 0, start + leading) + 1, content
        start = after
    if source[start:].strip():
        leading = len(source[start:]) - len(source[start:].lstrip())
        yield source.count('\n', 0, start + leading) + 1, source[start:].strip()


def context_for(result, title):
    return {"title": title, "focus": result.focus_id,
            "components": [{"id": e.id, "type": e.type, "text": e.text, "name": e.name,
                            "parent": e.parent_id, "properties": e.properties} for e in result.symbols],
            "positions": [{"target": s.resolved_id, "relative_to": s.target_id, "direction": s.properties['position']}
                          for s in result.ast if s.kind == 'position' and s.resolved_id and s.target_id]}


def _safe_reference(reference, result):
    if reference is None or reference.startswith(('safe:', 'unique:', 'ordinal:', 'position:', 'named:', 'all:')):
        return reference
    if reference == 'fields':
        return reference
    if any(reference in {e.name, e.properties.get('id'), e.text} for e in result.symbols):
        return 'named:' + reference
    typed = english_target(reference)
    if result.focus_explicit and any(e.id == result.focus_id and e.type == typed for e in result.symbols):
        return result.focus_id
    return safe_target(typed)


def _navigation_colors(result, statements):
    by_id = {e.id: e for e in result.symbols}
    for statement in statements:
        e = by_id.get(statement.resolved_id)
        if not e or e.type != 'nav' or 'background-color' not in statement.properties or 'background-color' not in e.properties:
            continue
        background = color(e.properties['background-color'])
        foreground = readable_foreground(background)
        for child in result.symbols:
            ancestor = by_id.get(child.parent_id)
            while ancestor and ancestor.id != e.id:
                ancestor = by_id.get(ancestor.parent_id)
            if ancestor and child.type == 'link' and (child.auto_foreground or not any(k in child.properties for k in {'color', 'text-color'})):
                child.properties['text-color'] = foreground
                child.auto_foreground = True


def compile_natural(source, *, converter, previous=None):
    """Copy/validate/commit candidate IR. The caller keeps previous on failure."""
    if previous is not None and not previous.success:
        raise ValueError('Updates require a successful prior compilation.')
    result = deepcopy(previous) if previous else CompilationResult()
    result.html = result.css = None
    result.diagnostics = []
    title = previous.page_tree.title if previous else ''
    clauses = list(segment(source))
    if not clauses:
        result.diagnostics.append(Diagnostic('input', 1, 'Describe the page or a change to an existing component.'))
        return result
    if len(clauses) > 128 or len(result.symbols) > 500:
        result.diagnostics.append(Diagnostic('input', 1, 'This page is too large. Use at most 128 instructions per edit and 500 components.'))
        return result
    for line, instruction in clauses:
        started = perf_counter()
        partial = CompilationResult()
        normalized = normalize(instruction)
        for sentence in normalized:
            sentence.line, sentence.original = line, instruction
            parse_sentence(sentence, partial)
        unresolved_position_source = False
        if not partial.diagnostics and not any(s.kind == 'add' for s in partial.ast):
            for statement in partial.ast:
                if statement.kind == 'position' and statement.reference not in {'it', 'this'}:
                    probe = deepcopy(result)
                    lookup(probe, _safe_reference(statement.reference, probe), line)
                    unresolved_position_source = unresolved_position_source or bool(probe.diagnostics)
        trace = {"line": line, "input": instruction, "route": 'deterministic', "operations": []}
        if partial.diagnostics or unresolved_position_source:
            try:
                dsl, conversion = converter.convert(instruction, context_for(result, title))
                trace.update(conversion)
                partial = CompilationResult()
                normalized = normalize(dsl)
                if not normalized or len(normalized) > 128:
                    raise IntentError('The interpretation produced too many instructions.')
                for sentence in normalized:
                    sentence.line, sentence.original = line, instruction
                    parse_sentence(sentence, partial)
            except IntentError as error:
                trace.update(route='rejected', message=str(error))
                partial = CompilationResult(diagnostics=[Diagnostic(error.phase, line, str(error))])
        trace['dsl'] = [sentence.normalized for sentence in normalized]
        result.sentences.extend(normalized)
        result.tokens.extend(partial.tokens)
        result.diagnostics.extend(partial.diagnostics)
        if not partial.diagnostics:
            old_ids = {e.id for e in result.symbols}
            for statement in partial.ast:
                aliases = {'background': 'background-color', 'colour': 'color', 'background-colour': 'background-color',
                           'corner-radius': 'border-radius'}
                statement.properties = {aliases.get(k, k): v.replace(' ', '-') if aliases.get(k, k).endswith('color') and v.replace(' ', '-') in COLORS else v
                                        for k, v in statement.properties.items()}
                # Compiler DSL remains valid, while user-level type/pronoun edits
                # require a unique selection instead of silently choosing latest.
                if statement.kind in {'format', 'position', 'attach', 'wrap'}:
                    if re.search(r'\b(?:this|that)\s+(?:external\s+)?' + re.escape(statement.reference or '') + r'\b', instruction, re.I):
                        focused = next((e for e in result.symbols if e.id == result.focus_id), None)
                        if focused and focused.type == statement.reference:
                            statement.reference = 'safe:it'
                    statement.reference = _safe_reference(statement.reference, result)
                if statement.kind == 'position':
                    statement.target_type = _safe_reference(statement.target_type, result)
                if statement.kind == 'attach':
                    statement.parent_reference = _safe_reference(statement.parent_reference, result)
                if statement.kind == 'format' and 'color' in statement.properties and not re.match(r'\s*(?:set|configure|change)', instruction, re.I):
                    selected = lookup(result, statement.reference, line, plural=True)
                    if selected and all(e.type == 'nav' for e in selected):
                        statement.properties['background-color'] = statement.properties.pop('color')
                # A new placement instruction supersedes the previous placement
                # of the same source on that axis, preserving other constraints.
                if statement.kind == 'position':
                    selected = lookup(result, statement.reference, line)
                    if selected:
                        axis = statement.properties['position'] in {'left', 'right'}
                        result.ast = [s for s in result.ast if not (s.kind == 'position' and s.resolved_id == selected[0].id
                            and (s.properties['position'] in {'left', 'right'}) == axis)]
                result.ast.append(statement)
                title = resolve(result, title=title, statements=[statement], finalize=False)
                if statement.kind == 'format' and statement.reference == 'page':
                    if any(k in statement.properties for k in {'color', 'text-color'}):
                        result.auto_page_foreground = False
                    elif 'background-color' in statement.properties and (result.auto_page_foreground or not any(k in result.page_properties for k in {'color', 'text-color'})):
                        result.page_properties['text-color'] = readable_foreground(result.page_properties['background-color'])
                        result.auto_page_foreground = True
                _navigation_colors(result, [statement])
                if statement.kind == 'format' and statement.resolved_id:
                    for e in result.symbols:
                        if e.id == statement.resolved_id and any(k in statement.properties for k in {'color', 'text-color'}):
                            e.auto_foreground = False
                # Within a multi-operation clause, later operations can say "it".
                if statement.resolved_id:
                    result.focus_id = statement.resolved_id
                    result.focus_explicit = statement.kind != 'add'
            new = [e for e in result.symbols if e.id not in old_ids]
            roots = [e for e in new if e.parent_id not in {n.id for n in new}]
            if new:
                result.focus_id = roots[0].id if len(roots) == 1 else None
                result.focus_explicit = False
        trace['latency_ms'] = round((perf_counter() - started) * 1000, 3)
        result.interpretations.append(trace)
        if result.diagnostics:
            break  # Context after an invalid edit must never feed further edits.
    if len(result.symbols) > 500:
        result.diagnostics.append(Diagnostic('input', 1, 'A page can contain at most 500 components.'))
    if result.diagnostics:
        return result
    validate_relationships(result)
    if result.diagnostics:
        return result
    result.page_tree = build_page_tree(result, title)
    if result.diagnostics:
        return result
    check_accessibility(result)
    if not result.diagnostics:
        result.page_tree = optimize_page_tree(result.page_tree)
        result.html, result.css = generate(title, result.symbols, result.page_tree)
    return result
