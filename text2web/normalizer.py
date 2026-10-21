"""Normalize instruction words without changing quoted content or line numbers."""

import re
import json

from .model import Sentence
from .english import expand_english

SYNONYMS = {"create": "add", "insert": "add"}
SYNONYMS.update({
    "place": "put", "move": "put", "over": "above", "under": "below",
    "large": "big", "regular": "medium",
})
# Quoted strings use JSON escapes, including \" and \\.
QUOTED = re.compile(r'("(?:[^"\\\r\n]|\\.)*")')
WORDS = re.compile(r"[A-Za-z]+")


def normalize(source: str) -> list[Sentence]:
    sentences = []
    for line, original in enumerate(source.splitlines(), start=1):
        if not original.strip():
            continue
        chunks = []
        start = 0
        quoted = None
        escaped = False
        for index, character in enumerate(original):
            if quoted and escaped:
                escaped = False
            elif quoted and character == "\\":
                escaped = True
            elif quoted and character == quoted:
                quoted = None
            elif not quoted and (character == '"' or character == "'" and (index == 0 or not original[index - 1].isalnum())):
                quoted = character
            elif not quoted and character == "." and (index + 1 == len(original) or original[index + 1].isspace() or original[index + 1] == "."):
                remainder = original[index + 1:]
                if remainder.strip():
                    chunks.append(original[start:index + 1])
                    start = index + 1
        chunks.append(original[start:])
        for chunk in chunks:
            if not chunk.strip():
                continue
            raw_chunk = chunk.strip()
            chunk = re.sub(r'''"(?:[^"\\]|\\.)*"|(?<!\w)'((?:[^'\\]|\\.)*)' '''.strip(),
                           lambda m: json.dumps(m[1].replace("\\'", "'")) if m[1] is not None else m[0], chunk)
            try:
                expanded = expand_english(chunk)
            except (ValueError, UnicodeError):
                # Leave malformed literals to the parser's source-line diagnostics.
                expanded = None
            for instruction in expanded or [chunk]:
                parts = QUOTED.split(instruction)
                for index in range(0, len(parts), 2):
                    parts[index] = WORDS.sub(
                        lambda match: SYNONYMS.get(match[0].lower(), match[0].lower()),
                        parts[index],
                    )
                    parts[index] = re.sub(r"\s+", " ", parts[index])
                sentences.append(Sentence(line, raw_chunk, "".join(parts).strip()))
    return sentences
