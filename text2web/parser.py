"""Lark lexical analysis and LALR parsing for the controlled-English language."""

import json
from pathlib import Path

from lark import Lark, Token, UnexpectedInput

from .model import CompilationResult, Diagnostic, Sentence, Statement

PARSER = Lark(
    Path(__file__).with_name("grammar.lark").read_text(encoding="utf-8"),
    parser="lalr",
    lexer="basic",
    propagate_positions=True,
)


def parse_sentence(sentence: Sentence, result: CompilationResult) -> None:
    try:
        # Use Lark's own lexer for the visible token stream, including partial
        # tokens before lexical errors. The parser uses that same lexer grammar.
        for token in PARSER.lex(sentence.normalized):
            result.tokens.append({
                "line": sentence.line,
                "type": token.type,
                "value": str(token),
            })
        tree = PARSER.parse(sentence.normalized).children[0]
    except UnexpectedInput:
        result.diagnostics.append(Diagnostic(
            "syntax", sentence.line,
            'Unsupported or malformed instruction. Use the sentence guide; '
            'provide explicit text, list items, form options and destinations. '
            'Separate instructions with full stops and quote content. '
            'Backend submission, authentication, storage and arbitrary HTML/CSS are not supported.',
        ))
        return

    child_tokens = [token for token in tree.children if isinstance(token, Token)]
    fields = {token.type: str(token) for token in child_tokens}
    try:
        strings = [json.loads(str(token)) for token in child_tokens if token.type == "STRING"]
        for token in tree.scan_values(lambda value: isinstance(value, Token) and value.type == "STRING"):
            value = json.loads(str(token))
            value.encode("utf-8")
    except (ValueError, UnicodeError):
        result.diagnostics.append(Diagnostic(
            "syntax", sentence.line,
            'Invalid quoted text. Use JSON escapes such as \\" for a quote '
            'and \\\\ for a backslash; Unicode text must be valid.',
        ))
        return

    text = strings[-1] if strings else None
    if tree.data == "component":
        properties = {}
        parent = None
        for child in tree.children:
            if getattr(child, "data", None) == "property":
                key, value = [json.loads(str(t)) for t in child.children if t.type == "STRING"]
                if key in properties:
                    result.diagnostics.append(Diagnostic("syntax", sentence.line, f'Duplicate property "{key}".'))
                    return
                properties[key] = value
            elif getattr(child, "data", None) == "parent":
                parent = json.loads(str(child.children[-1]))
        statement = Statement("add", sentence.line, strings[0], strings[1], properties,
                              parent_reference=parent, extended=True)
    elif tree.data == "configure":
        statement = Statement("format", sentence.line, properties={strings[1]: strings[2]}, reference=strings[0], extended=True)
    elif tree.data == "attach":
        statement = Statement("attach", sentence.line, reference=strings[0], parent_reference=strings[1], extended=True)
    elif tree.data == "wrap":
        statement = Statement("wrap", sentence.line, reference=strings[0], properties={"href": strings[1]}, extended=True)
    elif tree.data == "arrange":
        statement = Statement("position", sentence.line, reference=strings[0], target_type=strings[1],
                              properties={"position": fields["DIRECTION"]}, extended=True)
    elif tree.data == "page":
        statement = Statement("page", sentence.line, text=text)
    elif tree.data == "add_element":
        if fields["ELEMENT"] == "image":
            result.diagnostics.append(Diagnostic(
                "syntax", sentence.line,
                'Add images with: Add an image "file.png" described as "Description".',
            ))
            return
        properties = {name.lower(): fields[name] for name in ("SIZE", "COLOR") if name in fields}
        statement = Statement("add", sentence.line, fields["ELEMENT"], text, properties)
    elif tree.data == "add_image":
        if fields["ELEMENT"] != "image":
            result.diagnostics.append(Diagnostic(
                "syntax", sentence.line,
                'Add images with: Add an image "file.png" described as "Description".',
            ))
            return
        statement = Statement(
            "add", sentence.line, "image", strings[1], {"src": strings[0]},
        )
    elif tree.data == "position_element":
        statement = Statement(
            "position", sentence.line,
            properties={"position": fields["DIRECTION"]},
            reference=fields["REFERENCE"], target_type=fields["ELEMENT"],
        )
    elif "BOLD" in fields:
        statement = Statement(
            "format", sentence.line,
            properties={"font-weight": "bold"}, reference=fields["REFERENCE"],
        )
    elif "FONT" in fields:
        statement = Statement(
            "format", sentence.line,
            properties={"font-family": fields["FONT"]}, reference=fields["REFERENCE"],
        )
    elif "SIZE" in fields:
        statement = Statement(
            "format", sentence.line,
            properties={"size": fields["SIZE"]}, reference=fields["REFERENCE"],
        )
    else:
        statement = Statement(
            "format", sentence.line,
            properties={"color": fields["COLOR"]}, reference=fields["REFERENCE"],
        )
    result.ast.append(statement)
