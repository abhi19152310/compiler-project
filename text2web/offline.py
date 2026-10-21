"""Compositional offline extraction for common English; no claim of model NLP."""

import json
import re

from .english import Q, items, slug
from .properties import COLORS, TYPES

ALIASES = {'navbar': 'nav', 'navigation': 'nav', 'navigation bar': 'nav', 'menu': 'nav',
           'navigation menu': 'nav', 'nav bar': 'nav', 'webpage': 'page', 'website': 'page',
           'web page': 'page', 'homepage': 'page', 'main content': 'main', 'main section': 'main',
           'picture': 'image', 'photo': 'image', 'title': 'heading', 'text': 'paragraph', 'layout': 'page'}
TYPE_WORDS = '|'.join(sorted([*TYPES, *ALIASES], key=len, reverse=True))
COLOR_WORDS = '|'.join(sorted([key.replace('-', r'[- ]') for key in COLORS], key=len, reverse=True)) + '|#[0-9a-fA-F]{6}'


def text(value):
    value = value.strip().rstrip('.').strip()
    if re.fullmatch(Q, value):
        return json.loads(value)
    return value


def target(value):
    value = value.strip()
    if re.fullmatch(Q, value):
        return 'name:' + json.loads(value)
    value = re.sub(r'^(?:the|this|that|a|an)\s+', '', value.lower()).strip()
    if value in {'it', 'this', 'that'}:
        return 'it'
    if m := re.fullmatch(r'(.+?) (?:on|to) the (left|right)(?: side)?', value):
        kind = ALIASES.get(m[1], m[1])
        return m[2] + ':' + kind
    if m := re.fullmatch(r'(first|second|third|last) (.+)', value):
        return m[1] + ':' + ALIASES.get(m[2], m[2])
    if value.startswith('all '):
        kind = ALIASES.get(value[4:].removesuffix('s'), value[4:].removesuffix('s'))
        return 'all:' + kind
    return ALIASES.get(value, value)


def create(kind, value='', properties=None, parent=None):
    return {'op': 'create', 'type': kind, 'text': value, 'properties': properties or {}, 'parent': parent}


def style(reference, properties):
    return {'op': 'style', 'target': reference, 'properties': properties}


def interpret(instruction, context=None):
    s = instruction.strip().removesuffix('.').strip()
    s = re.sub(r'^(?:(?:please|kindly)\s+|(?:can|could|would) you\s+)', '', s, flags=re.I)
    s = re.sub(r'^(?:build|design|generate|create|insert|show|display)\b(?: me)?', 'add', s, flags=re.I)
    s = re.sub(r'^make(?: me)? (?=(?:a |an )?(?:web ?page|website|homepage|page)\b(?! background)|(?:a |an )?(?:navigation bar|navbar|nav bar|navigation menu|menu|nav)\b(?: with|$))', 'add ', s, flags=re.I)
    s = re.sub(r'^put (?=(?:a|an) (?:small |medium |large |big )?(?:heading|paragraph|button|card) (?:that )?(?:saying|says|reading|labelled|labeled|called)\b)', 'add ', s, flags=re.I)
    # Narrow spelling normalization in command/type words, leaving payload untouched.
    s = re.sub(r'\b(?:navigaton|naviagtion)\b', 'navigation', s, count=1, flags=re.I)

    def match(pattern):
        return re.fullmatch(pattern, s, re.I)
    def result(*operations):
        return {'operations': list(operations)}
    def clarify(message):
        return result({'op': 'clarify', 'message': message})

    # Parse backgrounds before generic color edits so "background" is never
    # mistaken for a component name. An omitted target means the page.
    if m := match(rf'(?:change|set|make) (?:the )?(?:(.+?)(?:\'s)? )?background(?: colou?r)? (?:to )?({COLOR_WORDS})'):
        return result(style(target(m[1]) if m[1] else 'page', {'background-color': m[2].lower().replace(' ', '-')}))
    if match(r'(?:change|set|make) (?:the )?background(?: colou?r)?'):
        return clarify('Which background color should I use?')

    if m := match(r'(?:add (?:me )?(?:a |an |the )?(?:web ?page|website|homepage|page)(?: (?:called|named|titled|for))?|i (?:need|want|would like) (?:a |an )?(?:web ?page|website|homepage|page)(?: (?:called|named|titled|for))?) (.+)'):
        return result({'op': 'page', 'title': text(m[1])})
    if match(r'(?:add|i need|i want) (?:a |an )?(?:web ?page|website|homepage|page)'):
        return clarify('What should the page be called?')

    if m := match(rf'add (?:a |an |the )?(?:({COLOR_WORDS}) )?(?:navigation bar|navbar|nav bar|navigation menu|menu|nav)(?: with (.+))?'):
        if not m[2]:
            return clarify('Which navigation links should appear? Please provide their labels.')
        labels = items(re.sub(r' links?$', '', m[2], flags=re.I))
        name = 'navigation-' + str(len((context or {}).get('components', [])) + 1)
        props = {'name': name, 'aria-label': 'Main navigation', 'responsive': 'true'}
        operations = [create('nav', properties=props)]
        for label in labels:
            if not slug(label):
                return clarify('Please provide meaningful navigation labels and destinations.')
            operations.append(create('link', label, {'href': '/' if label.lower() == 'home' else '/' + slug(label)}, 'name:' + name))
        if m[1]:
            operations.append(style('name:' + name, {'background-color': m[1].lower().replace(' ', '-')}))
        return result(*operations)

    # Extract an optional layout relation independently of the created component.
    relation = None
    relation_match = re.search(r'\s+(below|above|beside|to the (?:left|right)(?: side)? of)\s+(.+)$', s, re.I)
    if relation_match and not any(q.start() <= relation_match.start() < q.end() for q in re.finditer(Q, s)):
        direction = relation_match[1].lower()
        direction = 'right' if direction == 'beside' else 'left' if 'left' in direction else 'right' if 'right' in direction else direction
        relation = {'op': 'position', 'target': 'it', 'direction': direction, 'relative_to': target(relation_match[2])}
        s = s[:relation_match.start()]
    if m := match(rf'add (?:a |an |the )?(?:(small|medium|large|big) )?(?:({COLOR_WORDS}) )?(heading|paragraph|button|card|image|picture|photo)(?: (?:that )?(?:saying|says|reading|labelled|labeled|called|with (?:the )?text) (.+))?'):
        kind = ALIASES.get(m[3].lower(), m[3].lower())
        if kind == 'image':
            return clarify('Which image should I use? Provide its URL or filename and an alternative-text description.')
        content = text(m[4]) if m[4] else ''
        if not content and kind != 'card':
            return clarify(f'What should the {kind} say?')
        props = {}
        if m[1]:
            props['size'] = m[1].lower()
        if m[2]:
            props['color'] = m[2].lower().replace(' ', '-')
        return result(create(kind, content, props), *([relation] if relation else []))
    if m := match(r'add (?:an? )?(.+?) (button|heading|card)'):
        if re.match(r'(?:an? )?(?:image|photo|picture)\b', m[1], re.I):
            return clarify('Which image should I use? Provide its URL or filename and an alternative-text description.')
        value = text(m[1])
        if re.search(r'\b(?:large|small|rounded|another|responsive)\b', value, re.I):
            if value.lower() != 'another' or m[2].lower() != 'card':
                return None
            value = ''
        return result(create(m[2].lower(), value), *([relation] if relation else []))

    if m := match(rf'(?:change|set|make) (.+?)(?:\'s)? colou?r (?:to )?({COLOR_WORDS})'):
        return result(style(target(m[1]), {'color': m[2].lower().replace(' ', '-')}))
    if m := match(rf'(?:make|turn|paint) (.+?) (?:to )?({COLOR_WORDS})'):
        reference, value = target(m[1]), m[2].lower().replace(' ', '-')
        return result(style(reference, {'background-color' if reference.endswith(':nav') or reference == 'nav' else 'color': value}))
    if m := match(rf'(?:change|set|make) (.+?)(?:\'s)? (?:background(?: colou?r)?|colou?r) (?:to )?({COLOR_WORDS})'):
        key = 'background-color' if 'background' in s.lower() else 'color'
        return result(style(target(m[1]), {key: m[2].lower().replace(' ', '-')}))
    if m := match(rf'(?:add|apply|give) ({COLOR_WORDS}) colou?r to (.+)'):
        reference = target(m[2])
        return result(style(reference, {'background-color' if reference == 'nav' else 'color': m[1].lower().replace(' ', '-')}))
    if m := match(r'(?:make|give) (.+?) (?:rounded|rounded corners|rounded edges)(?: of (\d+) pixels?)?'):
        return result(style(target(m[1]), {'border-radius': (m[2] or '12') + 'px'}))
    if m := match(r'make (.+?) (?:responsive|adapt)(?: for| on| to)? (?:mobile(?: devices)?|smaller screens)'):
        return result(style(target(m[1]), {'responsive': 'true'}))
    if m := match(r'(?:put|place|move) (.+?) (below|above|beside|to the left of|to the right of) (.+)'):
        direction = {'beside': 'right', 'to the left of': 'left', 'to the right of': 'right'}.get(m[2].lower(), m[2].lower())
        return result({'op': 'position', 'target': target(m[1]), 'direction': direction, 'relative_to': target(m[3])})
    if re.search(r'\b(?:database|authentication|authenticate|javascript|save (?:the )?data|send (?:an? )?email|log ?in)\b', s, re.I):
        return result({'op': 'unsupported', 'message': 'This compiler generates static pages. Submission, authentication, database storage and JavaScript actions are not implemented.'})
    return None
