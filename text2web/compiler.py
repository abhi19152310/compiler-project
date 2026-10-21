"""Compiler driver. No output generation occurs while blocking errors exist."""

from .codegen import generate
from .accessibility import check_accessibility
from .layout import build_page_tree, optimize_page_tree
from .model import CompilationResult, Diagnostic
from .normalizer import normalize
from .parser import parse_sentence
from .semantics import resolve


def compile_source(source: str, *, nlp_converter=None) -> CompilationResult:
    if getattr(nlp_converter, 'structured', False):
        from .natural import compile_natural
        return compile_natural(source, converter=nlp_converter)
    result = CompilationResult(sentences=normalize(source))
    if not result.sentences:
        result.diagnostics.append(Diagnostic("input", 1, "Enter at least a page-title instruction."))
        return result
    for sentence in list(result.sentences):
        partial = CompilationResult()
        parse_sentence(sentence, partial)
        if partial.diagnostics and nlp_converter is not None:
            # Optional application-supplied NLP adapter returns only DSL text.
            # It never supplies AST nodes, HTML, CSS or symbol-table mutations.
            try:
                converted = nlp_converter(sentence.original)
                if not isinstance(converted, str) or not converted.strip() or len(converted) > 32768:
                    raise ValueError('NLP output must be non-empty DSL text of at most 32768 characters.')
                replacements = normalize(converted)
                partial = CompilationResult()
                for replacement in replacements:
                    replacement.line = sentence.line
                    replacement.original = sentence.original
                    parse_sentence(replacement, partial)
                index = result.sentences.index(sentence)
                result.sentences[index:index + 1] = replacements
            except Exception:
                partial = CompilationResult(diagnostics=[Diagnostic('normalization', sentence.line,
                    'NLP conversion failed. Supply a supported instruction with explicit content and destinations.')])
        result.tokens.extend(partial.tokens)
        result.ast.extend(partial.ast)
        result.diagnostics.extend(partial.diagnostics)
    # Continue parsing independent lines, but never resolve against a partial AST.
    if result.diagnostics:
        return result
    title = resolve(result)
    if result.diagnostics:
        return result
    result.page_tree = build_page_tree(result, title)
    check_accessibility(result)
    if not result.diagnostics:
        result.page_tree = optimize_page_tree(result.page_tree)
        result.html, result.css = generate(title, result.symbols, result.page_tree)
    return result


def compile_update(previous: CompilationResult, source: str, *, nlp_converter=None) -> CompilationResult:
    from .natural import compile_natural
    from .nlp import interpreter_from_env
    return compile_natural(source, previous=previous, converter=nlp_converter or interpreter_from_env())
