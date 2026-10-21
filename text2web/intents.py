"""Strict, data-only intent schema and translation into the existing DSL."""

import re

from .english import component, configure, quote
from .properties import ALLOWED, TYPES


class IntentError(ValueError):
    def __init__(self, message, phase="interpretation"):
        super().__init__(message)
        self.phase = phase


FIELDS = {
    "page": {"title": {"type": "string", "minLength": 1, "maxLength": 4096}},
    "create": {"type": {"enum": sorted(TYPES)}, "text": {"type": "string", "maxLength": 8192},
               "properties": {"type": "object", "propertyNames": {"enum": sorted(ALLOWED)},
                              "additionalProperties": {"type": "string", "maxLength": 4096}},
               "parent": {"type": ["string", "null"], "maxLength": 256}},
    "style": {"target": {"type": "string", "minLength": 1, "maxLength": 256},
              "properties": {"type": "object", "minProperties": 1, "propertyNames": {"enum": sorted(ALLOWED)},
                             "additionalProperties": {"type": "string", "maxLength": 4096}}},
    "position": {"target": {"type": "string", "minLength": 1, "maxLength": 256},
                 "relative_to": {"type": "string", "minLength": 1, "maxLength": 256},
                 "direction": {"enum": ["left", "right", "above", "below"]}},
    "attach": {"target": {"type": "string", "minLength": 1, "maxLength": 256}, "parent": {"type": "string", "minLength": 1, "maxLength": 256}},
    "clarify": {"message": {"type": "string", "minLength": 1, "maxLength": 1000}},
    "unsupported": {"message": {"type": "string", "minLength": 1, "maxLength": 1000}},
}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["operations"],
    "properties": {"operations": {"type": "array", "minItems": 1, "maxItems": 64,
        "items": {"oneOf": [{"type": "object", "additionalProperties": False,
            "properties": {"op": {"const": op}, **fields}, "required": ["op", *fields]}
            for op, fields in FIELDS.items()]}}},
}


def validate_intents(data):
    """Validate every schema constraint independently of model/provider promises."""
    if not isinstance(data, dict) or set(data) != {"operations"}:
        raise IntentError('The language model returned an invalid operation document.')
    operations = data["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= 64:
        raise IntentError('An interpretation must contain 1 to 64 supported operations.')
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("op"), str) or operation["op"] not in FIELDS:
            raise IntentError('The interpretation contains an unknown operation.')
        fields = FIELDS[operation["op"]]
        if set(operation) != {"op", *fields}:
            raise IntentError('The interpretation has missing or unsupported fields.')
        for key, schema in fields.items():
            value = operation[key]
            if value is None and schema.get("type") == ["string", "null"]:
                continue
            if schema.get("type") == "object":
                if not isinstance(value, dict) or len(value) < schema.get("minProperties", 0) or len(value) > len(ALLOWED):
                    raise IntentError('Properties must be a supported property map.')
                if any(k not in ALLOWED or not isinstance(v, str) or len(v) > 4096 for k, v in value.items()):
                    raise IntentError('The interpretation contains unsupported properties or non-text values.')
                continue
            if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 8192):
                raise IntentError('The interpretation has an invalid text field.')
            try:
                value.encode('utf-8')
            except UnicodeError as error:
                raise IntentError('The interpretation contains invalid Unicode.') from error
            if "enum" in schema and value not in schema["enum"]:
                raise IntentError('The interpretation requests an unsupported component or direction.')
    return operations


def safe_target(target):
    """User/model targets select uniquely; latest-by-type is never guessed."""
    if target in {"it", "this", "that"}:
        return "safe:it"
    if target == "page" or re.fullmatch(r'element\d+', target):
        return target
    if target in TYPES:
        return "unique:" + target
    if target.startswith("all:") and target[4:] in TYPES:
        return target
    if re.fullmatch(r'(?:first|second|third|last):[a-z]+', target):
        ordinal, kind = target.split(':')
        if kind in TYPES:
            return f'ordinal:{kind}:' + {"first": "1", "second": "2", "third": "3", "last": "-1"}[ordinal]
    if re.fullmatch(r'(?:left|right|above|below):[a-z]+', target) and target.split(':')[1] in TYPES:
        direction, kind = target.split(':')
        return f'position:{kind}:{direction}'
    return "named:" + target.removeprefix('name:')


def intents_to_dsl(data):
    operations = validate_intents(data)
    output = []
    for operation in operations:
        op = operation["op"]
        if op in {"clarify", "unsupported"}:
            raise IntentError(operation["message"], "clarification" if op == "clarify" else "unsupported")
        if op == "page":
            output.append(f'add a page titled {quote(operation["title"])}')
        elif op == "create":
            output.append(component(operation["type"], operation["text"], operation["properties"],
                                    safe_target(operation["parent"]) if operation["parent"] else None))
        elif op == "style":
            output.extend(configure(safe_target(operation["target"]), key, value) for key, value in operation["properties"].items())
        elif op == "attach":
            output.append(f'attach {quote(safe_target(operation["target"]))} {quote(safe_target(operation["parent"]))}')
        elif op == "position":
            output.append(f'arrange {quote(safe_target(operation["target"]))} {operation["direction"]} {quote(safe_target(operation["relative_to"]))}')
    return '\n'.join(output)
