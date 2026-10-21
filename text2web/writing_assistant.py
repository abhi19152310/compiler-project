"""Read-only, compiler-checked guidance. Never calls a model or saves a page."""

from collections import Counter
import json
import re

from .compiler import compile_source, compile_update
from .english import Q, items, quote
from .natural import segment
from .nlp import NaturalInterpreter
from .offline import ALIASES, target
from .properties import COLORS, SIZES

COLOR_EQUIVALENTS = {'yellow': '#ffff00', 'orange': '#ffa500', 'purple': '#800080', 'pink': '#ffc0cb'}
COLOR_PATTERN = '|'.join(re.escape(c).replace(r'\-', '[- ]') for c in sorted(set(COLORS) | set(COLOR_EQUIVALENTS), key=len, reverse=True)) + '|#[0-9a-fA-F]{6}'
NAMES = {'nav': 'navigation bar', 'paragraph': 'paragraph', 'image': 'image', 'main': 'main section'}


def field(key, label, default='', options=None):
    return {'key': key, 'label': label, 'default': default, 'options': options}


def catalog():
    colors = sorted(COLORS)
    return [
        {'id': 'page', 'label': 'Page', 'fields': [field('text', 'Page title', 'My Page')]},
        {'id': 'navigation', 'label': 'Navigation', 'fields': [field('text', 'Link labels (comma-separated)', 'Home, About, Contact')]},
        {'id': 'heading', 'label': 'Heading', 'fields': [field('text', 'Heading text', 'Welcome'), field('size', 'Text size', 'big', list(SIZES))]},
        {'id': 'paragraph', 'label': 'Paragraph', 'fields': [field('text', 'Paragraph text', 'Welcome to our website.')]},
        {'id': 'button', 'label': 'Button', 'fields': [field('text', 'Button text', 'Register')]},
        {'id': 'image', 'label': 'Image', 'fields': [field('src', 'Image URL or filename'), field('alt', 'Image description')]},
        {'id': 'cards', 'label': 'Cards', 'fields': [field('text', 'Card titles (comma-separated)', 'Web Development, AI, Cloud Computing')]},
        {'id': 'form', 'label': 'Contact form', 'fields': []},
        {'id': 'background', 'label': 'Background', 'fields': [field('target', 'Component', 'the page', []), field('color', 'Color', 'green', colors)]},
        {'id': 'text-color', 'label': 'Text color', 'fields': [field('target', 'Component', 'the page', []), field('color', 'Color', 'black', colors)]},
        {'id': 'rounded', 'label': 'Rounded corners', 'fields': [field('target', 'Component', '', []), field('radius', 'Corner radius (pixels)', '12')]},
        {'id': 'responsive', 'label': 'Mobile layout', 'fields': []},
    ]


def _literal(value):
    value = value.strip().removesuffix('.').strip()
    if re.fullmatch(Q, value):
        return json.loads(value)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _list(value):
    labels = items(value)
    if not labels:
        raise ValueError('Please supply the actual labels or titles.')
    quoted = [quote(label) for label in labels]
    return ', '.join(quoted[:-1]) + ' and ' + quoted[-1] if len(quoted) > 1 else quoted[0]


def _color(value):
    value = value.strip().lower().replace(' ', '-')
    if value in COLORS or re.fullmatch(r'#[0-9a-f]{6}', value):
        return value
    return COLOR_EQUIVALENTS.get(value)


def _utf16(value):
    return len(value.encode('utf-16-le')) // 2


def instruction_at(source, cursor):
    """Browser cursors use UTF-16 offsets; Python slices use Unicode codepoints."""
    position, units = 0, 0
    for index, char in enumerate(source):
        length = _utf16(char)
        if units + length > cursor:
            break
        units += length
        position = index + 1
    seek = 0
    for _, instruction in segment(source):
        start = source.find(instruction, seek)
        if start < 0:
            continue
        end = start + len(instruction)
        seek = end
        # Consume a terminal full stop so applying a sentence never creates '..'.
        if end < len(source) and source[end] in '.!?':
            end += 1
        if start <= position <= end:
            return start, end, source[start:end]
    return position, position, ''


def _compile(source, previous=None):
    interpreter = NaturalInterpreter()  # Suggestions never trigger model/network calls.
    return compile_update(previous, source, nlp_converter=interpreter) if previous else compile_source(source, nlp_converter=interpreter)


def targets(result):
    choices = [{'value': 'the page', 'label': 'Page', 'type': 'page'}] if result and result.page_tree else []
    if not result:
        return choices
    counts = Counter(e.type for e in result.symbols)
    seen = Counter()
    for element in result.symbols:
        if element.type not in {'nav', 'heading', 'paragraph', 'button', 'image', 'main', 'section', 'container', 'card', 'footer', 'header', 'aside', 'form', 'link'}:
            continue
        seen[element.type] += 1
        label = NAMES.get(element.type, element.type)
        if counts[element.type] == 1:
            reference = 'the ' + label
        elif element.name:
            reference = quote(element.name)
        elif element.text and sum(e.text == element.text for e in result.symbols) == 1:
            reference = quote(element.text)
        elif seen[element.type] <= 3:
            reference = 'the ' + ['first', 'second', 'third'][seen[element.type] - 1] + ' ' + label
        else:
            reference = quote(element.id)
        detail = element.name or element.text
        choices.append({'value': reference, 'type': element.type, 'label': label.capitalize() + (f' {seen[element.type]}' if counts[element.type] > 1 else '') + (f' — {detail[:60]}' if detail else '')})
    return choices


def _reference(value, result):
    typed = target(value)
    if typed == 'page':
        return 'the page'
    if typed == 'it' and result and result.focus_id:
        focused = next((e for e in result.symbols if e.id == result.focus_id), None)
        if focused:
            return next((c['value'] for c in targets(result) if c['value'] == quote(focused.id)),
                        'the ' + NAMES.get(focused.type, focused.type) if sum(e.type == focused.type for e in result.symbols) == 1 else quote(focused.name or focused.id))
    if typed in set(ALIASES.values()) | {'heading', 'paragraph', 'button', 'card', 'section', 'container', 'footer', 'header', 'aside', 'form', 'link'}:
        return 'the ' + NAMES.get(typed, typed)
    return value.strip()


def _compose(template, values):
    specs = {s['id']: s for s in catalog()}
    if template not in specs:
        raise ValueError('Choose one of the supported actions.')
    allowed = {f['key'] for f in specs[template]['fields']}
    if set(values) - allowed or any(not isinstance(v, str) or len(v) > 4096 for v in values.values()):
        raise ValueError('Use the fields shown for this action.')
    fields = {f['key']: values.get(f['key'], f['default']).strip() for f in specs[template]['fields']}
    for f in specs[template]['fields']:
        if not fields[f['key']]:
            raise ValueError(f'Please provide {f["label"].lower()}.')
        if f['options'] and fields[f['key']] not in f['options'] and f['key'] != 'color':
            raise ValueError('Choose a supported value from the list.')
    if template == 'page':
        return f'Create a page titled {quote(fields["text"])}.'
    if template == 'navigation':
        return f'Create a navigation bar with {_list(fields["text"])} links.'
    if template in {'heading', 'paragraph', 'button'}:
        size = fields.get('size', '')
        return f'Add a {size + " " if size else ""}{template} that says {quote(fields["text"])}.'
    if template == 'image':
        return f'Add an image {quote(fields["src"])} described as {quote(fields["alt"])}.'
    if template == 'cards':
        count = len(items(fields['text']))
        return f'Create {count} cards for {_list(fields["text"])}.'
    if template == 'form':
        return 'Create a contact form with name, email and message fields.'
    if template in {'background', 'text-color'}:
        color = _color(fields['color'])
        if not color:
            raise ValueError('Choose a supported color or enter a six-digit hex color.')
        return f'Set {fields["target"]} {"background-color" if template == "background" else "text-color"} to {quote(color)}.'
    if template == 'rounded':
        if not re.fullmatch(r'\d{1,4}', fields['radius']):
            raise ValueError('Use a corner radius from 0 to 9999 pixels.')
        return f'Set {fields["target"]} border-radius to {fields["radius"]} pixels.'
    return 'Make the layout responsive on mobile devices.'


def _corrections(instruction, result):
    s = instruction.strip().removesuffix('.').strip()
    candidates = []
    if m := re.fullmatch(r'(?:make|create|build|add)(?: me)? (?:a |an |the )?(?:web ?page|website|homepage|page) (?:named|called|titled)(?: (.+))?', s, re.I):
        if m[1]:
            candidates.append(('Page title', f'Create a page titled {quote(_literal(m[1]))}.'))
    if m := re.fullmatch(r'(?:make|create|add|build) (?:a |the )?(?:navigation bar|navbar|nav|menu)(?: with (.+))?', s, re.I):
        if m[1]:
            labels = re.sub(r' links?$', '', m[1], flags=re.I)
            candidates.append(('Navigation links', f'Create a navigation bar with {_list(labels)} links.'))
    # Color descriptions are accepted only when they map to a whitelisted name/hex.
    if m := re.fullmatch(r'(?:make|set|change) (?:(.+?) )?background(?:[- ]colou?r)?(?: to)?(?: (.+))?', s, re.I):
        color = _color(m[2] or '')
        if color:
            reference = _reference(m[1] or 'page', result)
            candidates.append(('Background color', f'Set {reference} background-color to {quote(color)}.'))
    if m := re.fullmatch(rf'(?:make|turn|paint) (.+?) (?:to )?({COLOR_PATTERN})', s, re.I):
        color = _color(m[2])
        if color:
            reference = _reference(m[1], result)
            kind = target(m[1])
            focused = next((e for e in result.symbols if e.id == result.focus_id), None) if result else None
            is_nav = kind == 'nav' or kind == 'it' and focused and focused.type == 'nav'
            candidates.append(('Component color', f'Set {reference} {"background-color" if is_nav else "color"} to {quote(color)}.'))
    if re.fullmatch(r'(?:add|create|insert|make|build)(?: a| an| the)?(?:\s+(?:heading|paragraph|button|image|card|navigation bar|navbar))?', s, re.I):
        kind = s.lower().split()[-1]
        keys = {'heading': 'heading', 'paragraph': 'paragraph', 'button': 'button', 'image': 'image', 'card': 'cards', 'navbar': 'navigation', 'bar': 'navigation'}
        for key in [keys[kind]] if kind in keys else ['heading', 'paragraph', 'button', 'navigation']:
            if key == 'image':
                continue  # Ask for an actual source/description through the builder.
            candidates.append(('Complete instruction', _compose(key, {})))
    return list(dict.fromkeys(candidates))[:4]


def suggest(source, cursor, *, previous=None, mode='new', template=None, values=None):
    start, end, instruction = instruction_at(source, cursor)
    before = source[:start]
    base = _compile(before, previous) if before.strip() else previous
    prefix_ok = base is None or base.success
    current = _compile(instruction, base) if instruction.strip() and prefix_ok else None
    whole = _compile(source, previous) if source.strip() else previous
    known = whole if whole and whole.success else base if base and base.success else previous
    available = targets(known)
    context_message = '' if prefix_ok else 'An earlier instruction needs attention first. Move the cursor to that instruction.'
    if mode == 'update' and previous is None:
        prefix_ok = False
        context_message = 'Compile a page before writing follow-up instructions.'

    def check(candidate, context=base):
        result = _compile(candidate, context) if prefix_ok else None
        note = ''
        # A transparent nav on an already dark page would leave default blue links
        # unreadable. Offer an explicit, reviewable background matching the page.
        if result and result.diagnostics and all(d.phase == 'accessibility' and 'contrast' in d.message for d in result.diagnostics) and candidate.startswith('Create a navigation bar with ') and context:
            background = context.page_properties.get('background-color')
            if background:
                candidate = candidate.replace('Create a navigation bar', f'Add a {background} navigation bar', 1)
                result = _compile(candidate, context)
                note = 'Uses the page background so navigation links remain readable.'
        ready = bool(result and result.success and prefix_ok)
        reason = context_message or (result.diagnostics[0].message if result and result.diagnostics else '')
        return {'text': candidate, 'ready': ready, 'message': reason or note}

    def replacement(candidate):
        suffix = source[end:]
        if suffix.startswith(';') or re.match(r'\s+(?:and(?: then)?|then)\s+', suffix, re.I):
            return candidate.removesuffix('.')
        return candidate

    suggestions = []
    correction_context = base if base and base.success else previous
    for label, candidate in _corrections(instruction, correction_context) if instruction.strip() else []:
        if candidate == instruction.strip():
            continue
        item = check(candidate)
        suggestions.append({'label': label, **item, 'replacement': replacement(item['text'])})
    status = 'supported' if current and current.success else 'needs_help' if instruction.strip() else 'empty'
    message = context_message or ('This instruction works with the earlier instructions. Compile to validate the entire page.' if status == 'supported' else
                                 'Choose a supported wording below, or build an instruction.' if status == 'needs_help' else 'Choose an action below to build a supported instruction.')
    builder = None
    if template:
        try:
            fields = dict(values or {})
            if template in {'background', 'text-color', 'rounded'}:
                reference = fields.get('target')
                if reference not in {c['value'] for c in available}:
                    raise ValueError('Choose an existing component. Add or compile it first.')
            candidate = _compose(template, fields)
            if template == 'page' and whole and whole.success and not (current and any(s.kind == 'page' for s in current.ast[len(base.ast) if base else 0:])):
                raise ValueError('A page title already exists. Select its instruction to change the wording.')
            replace = not instruction.strip() or not current or not current.success or template == 'page'
            if replace:
                item = check(candidate)
                builder = {**item, 'action': 'replace', 'replacement': replacement(item['text'])}
            elif whole and whole.success:
                builder = {**check(candidate, whole), 'action': 'insert'}
            else:
                builder = {'text': candidate, 'action': 'insert', 'ready': False, 'message': 'Fix the remaining instructions before adding another one.'}
        except (ValueError, UnicodeError) as error:
            builder = {'text': '', 'action': 'replace', 'ready': False, 'message': str(error)}
    return {'span': {'start': _utf16(source[:start]), 'end': _utf16(source[:end]), 'text': instruction},
            'status': status, 'message': message, 'targets': available, 'suggestions': suggestions, 'builder': builder}
