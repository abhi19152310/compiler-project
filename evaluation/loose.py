"""Loose-English benchmark for the local-model route.

Each case builds a page offline, then sends one loose instruction that the
offline rules cannot interpret. None of these sentences appear in the model
prompt's examples, so the score reflects unseen wording.

    python -m evaluation.loose [--backend ollama|gemma] [--model NAME] [--output results.json]
"""

import argparse
import json
import os
from io import BytesIO
from pathlib import Path
import sys
from time import perf_counter
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text2web.natural import compile_natural
from text2web.nlp import GemmaProvider, NaturalInterpreter, OllamaProvider, load_env_file

PAGE = 'Create a page called Sweet Crumbs.'
HEADING = PAGE + ' Add a big heading saying "Fresh Bread Daily".'
BUTTON = HEADING + ' Add a button saying "Order Now".'
NAV = PAGE + ' Add a navigation bar with Home, Menu and Contact.'


def find(result, kind, text=None):
    return [e for e in result.symbols if e.type == kind and (text is None or e.text == text)]


def children(result, element):
    return [e for e in result.symbols if e.parent_id == element.id]


def has_text(result, element, text):
    return element.text == text or any(has_text(result, c, text) for c in children(result, element))


def positioned(result, kind, direction, other):
    ids = {e.id: e.type for e in result.symbols}
    return any(s.kind == 'position' and s.properties.get('position') == direction
               and ids.get(s.resolved_id) == kind and ids.get(s.target_id) == other for s in result.ast)


def prop(elements, key, value):
    return len(elements) == 1 and elements[0].properties.get(key) == value


def three_cards(r):
    cards = find(r, 'card')
    return len(cards) == 3 and all(any(has_text(r, c, t) for c in cards) for t in ('Bread', 'Cakes', 'Cookies'))


CASES = [
    # (id, setup, instruction, check or None for an expected safe rejection)
    ('title-casual', None, "I'd love a homepage for my bakery, call it Sweet Crumbs.",
     lambda r: r.page_tree.title == 'Sweet Crumbs'),
    ('heading-slang', PAGE, 'Stick a big title at the top that reads Fresh Bread Daily.',
     lambda r: prop(find(r, 'heading', 'Fresh Bread Daily'), 'size', 'big') or prop(find(r, 'heading', 'Fresh Bread Daily'), 'size', 'large')),
    ('nav-compound', PAGE, 'Throw a menu bar on top with Home, Menu and Contact in a dark blue shade.',
     lambda r: len(find(r, 'nav')) == 1 and [l.text for l in find(r, 'link')] == ['Home', 'Menu', 'Contact']
     and find(r, 'nav')[0].properties.get('background-color') == 'dark-blue'),
    ('footer-text', PAGE, 'Add a footer saying Copyright 2026 Sweet Crumbs.',
     lambda r: len(find(r, 'footer')) == 1 and has_text(r, find(r, 'footer')[0], 'Copyright 2026 Sweet Crumbs')),
    ('button-below', HEADING, 'Under the title, drop in a button labelled Order Now.',
     lambda r: len(find(r, 'button', 'Order Now')) == 1 and positioned(r, 'button', 'below', 'heading')),
    ('rounded-that', BUTTON, 'Give that button round corners.',
     lambda r: bool(find(r, 'button')[0].properties.get('border-radius'))),
    ('page-bg', HEADING, 'Make the whole background a soft yellow.',
     lambda r: r.page_properties.get('background-color') == 'yellow'),
    ('cards-list', PAGE, 'I want three cards titled Bread, Cakes and Cookies.', three_cards),
    ('move-right', BUTTON, 'Shift the Order Now button so it sits to the right of the heading.',
     lambda r: positioned(r, 'button', 'right', 'heading')),
    ('paragraph-under', HEADING, 'Write a short line under the heading that says We bake every morning.',
     lambda r: len(find(r, 'paragraph', 'We bake every morning')) == 1 and positioned(r, 'paragraph', 'below', 'heading')),
    ('heading-red', HEADING, "I'd like the heading text in red please.",
     lambda r: prop(find(r, 'heading'), 'color', 'red') or prop(find(r, 'heading'), 'text-color', 'red')),
    ('center-question', HEADING, 'Can the heading be centered?',
     lambda r: prop(find(r, 'heading'), 'text-align', 'center')),
    ('serif', HEADING, 'Use a serif font for the heading.',
     lambda r: prop(find(r, 'heading'), 'font-family', 'serif')),
    ('link-url', PAGE, 'Drop a link to our Instagram at https://instagram.com/sweetcrumbs labelled Follow us.',
     lambda r: prop(find(r, 'link', 'Follow us'), 'href', 'https://instagram.com/sweetcrumbs')),
    ('section-nested', PAGE, 'Add an about us section with a paragraph saying Family owned since 1990.',
     lambda r: len(find(r, 'section')) == 1 and has_text(r, find(r, 'section')[0], 'Family owned since 1990')),
    ('bold-should', BUTTON, 'The button should be bold.',
     lambda r: prop(find(r, 'button'), 'font-weight', 'bold')),
    ('nav-bg-give', NAV, 'Give the nav bar a light grey background.',
     lambda r: find(r, 'nav')[0].properties.get('background-color') in {'light-grey', 'light-gray'}),
    ('padding', PAGE + ' Add a card saying "Daily Specials".', 'Put 20px of padding around the card.',
     lambda r: prop(find(r, 'card'), 'padding', '20px')),
    # Expected safe rejections: no page may be produced.
    ('neg-payments', BUTTON, 'Make the Order Now button actually take card payments.', None),
    ('neg-image', PAGE, 'Show off a picture of our storefront at the top.', None),
    ('neg-ambiguous', BUTTON + ' Add a button saying "Call Us".', 'I want the button to be green.', None),
    ('neg-vague', HEADING, 'Make everything look nicer.', None),
]


# Written before the final prompt revision and never used to tune it.
HOLDOUT = [
    ('h-title', None, 'Spin up a website for the Lakeside Book Club please',
     lambda r: r.page_tree.title.lower().endswith('lakeside book club')),
    ('h-heading', PAGE, 'Up top I want massive text reading Baked With Love',
     lambda r: prop(find(r, 'heading', 'Baked With Love'), 'size', 'big') or prop(find(r, 'heading', 'Baked With Love'), 'size', 'large')),
    ('h-nav', PAGE, 'Run a nav across the top with About, Recipes and Shop links',
     lambda r: len(find(r, 'nav')) == 1 and [l.text for l in find(r, 'link')] == ['About', 'Recipes', 'Shop']),
    ('h-blurb', HEADING, 'Beneath the heading add a blurb: Open seven days a week',
     lambda r: len(find(r, 'paragraph', 'Open seven days a week')) == 1 and positioned(r, 'paragraph', 'below', 'heading')),
    ('h-purple', BUTTON, 'The Order Now button would look better in purple',
     lambda r: find(r, 'button')[0].properties.get('background-color') == 'purple' or find(r, 'button')[0].properties.get('color') == 'purple'),
    ('h-align', HEADING, 'Could the heading be right-aligned instead?',
     lambda r: prop(find(r, 'heading'), 'text-align', 'right')),
    ('h-card-round', PAGE + ' Add a card saying "Daily Specials".', 'Change the card so its corners are rounded off',
     lambda r: bool(find(r, 'card')[0].properties.get('border-radius'))),
    ('h-footer', PAGE, 'At the very bottom put a footer that just says Made in Ohio',
     lambda r: len(find(r, 'footer')) == 1 and has_text(r, find(r, 'footer')[0], 'Made in Ohio')),
    ('h-nav-link', NAV, 'Add another link to the menu called Blog',
     lambda r: len(find(r, 'nav')) == 1 and any(l.text == 'Blog' and l.parent_id == find(r, 'nav')[0].id for l in find(r, 'link'))),
    ('h-left', BUTTON, 'Can the heading sit to the left of the button?',
     lambda r: positioned(r, 'heading', 'left', 'button')),
    ('h-small', HEADING + ' Add a paragraph saying "Since 1990".', 'Make the paragraph text small',
     lambda r: prop(find(r, 'paragraph'), 'size', 'small')),
    ('h-nav-blue', NAV, 'I want the menu bar to be dark blue',
     lambda r: find(r, 'nav')[0].properties.get('background-color') == 'dark-blue'),
    ('hn-newsletter', PAGE, 'Let people sign up for our newsletter and email them every week', None),
    ('hn-logo', PAGE, 'Add our logo in the corner', None),
    ('hn-which', BUTTON + ' Add a button saying "Call Us".', 'Change the colour of one of the buttons to red', None),
    ('hn-copy', PAGE, 'Write some marketing text for us', None),
]


class Recorder:
    """Wraps urlopen to keep token counts and timings for each call."""

    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout):
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(262145)
        try:
            envelope = json.loads(raw)
            if 'usageMetadata' in envelope:  # Gemini API
                usage = envelope['usageMetadata']
                envelope = {'eval_count': usage.get('candidatesTokenCount'), 'prompt_eval_count': usage.get('promptTokenCount')}
            self.calls.append({k: envelope.get(k) for k in ('eval_count', 'prompt_eval_count', 'load_duration', 'total_duration')})
        except ValueError:
            pass
        return BytesIO(raw)


def run(backend, model, url, timeout, cases):
    recorder = Recorder()
    if backend == 'gemma':
        load_env_file(Path(__file__).resolve().parents[1] / '.env')
        provider = GemmaProvider(model=model or os.environ.get('TEXT2WEB_GEMMA_MODEL', 'gemma-4-26b-a4b-it'),
                                 api_key=os.environ.get('GEMINI_API_KEY'), timeout=timeout, opener=recorder)
    else:
        provider = OllamaProvider(model=model or 'qwen2.5:3b', base_url=url, timeout=timeout, opener=recorder)
    if hasattr(provider, 'warm'):
        started = perf_counter()
        provider.warm()
        print(f'warm-up {perf_counter() - started:.1f}s (model load and prompt cache, as the app does at startup)')
    model_converter = NaturalInterpreter(provider)
    offline = NaturalInterpreter()
    rows = []
    for case_id, setup, instruction, check in cases:
        previous = compile_natural(setup, converter=offline) if setup else None
        if previous is not None and not previous.success:
            raise SystemExit(f'{case_id}: setup failed offline: {previous.diagnostics}')
        calls = len(recorder.calls)
        started = perf_counter()
        result = compile_natural(instruction, converter=model_converter, previous=previous)
        seconds = perf_counter() - started
        new = result.interpretations[len(previous.interpretations) if previous else 0:]
        routes = [t['route'] for t in new]
        if check is None:
            # A correct rejection asks or refuses; an accidental compile error
            # after the model invented content does not count.
            passed = not result.success and result.diagnostics[0].phase in {'clarification', 'unsupported'}
        else:
            try:
                passed = result.success and bool(check(result))
            except (IndexError, AttributeError):
                passed = False
        stats = recorder.calls[calls:]
        rows.append({'id': case_id, 'instruction': instruction, 'passed': passed, 'success': result.success,
                     'routes': routes, 'seconds': round(seconds, 2),
                     'output_tokens': sum(c.get('eval_count') or 0 for c in stats),
                     'prompt_tokens': sum(c.get('prompt_eval_count') or 0 for c in stats),
                     'load_seconds': round(sum(c.get('load_duration') or 0 for c in stats) / 1e9, 2),
                     'message': result.diagnostics[0].message if result.diagnostics else None,
                     'phase': result.diagnostics[0].phase if result.diagnostics else None,
                     'dsl': [d for t in new for d in t.get('dsl', [])]})
        row = rows[-1]
        print(f"{'PASS' if passed else 'FAIL'} {seconds:6.1f}s {row['output_tokens']:5} tok  {case_id:16} {','.join(routes)}"
              + (f"  | {row['phase']}: {row['message'][:90]}" if row['message'] else ''))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['ollama', 'gemma'], default='ollama')
    parser.add_argument('--model', help='default: qwen2.5:3b for ollama, TEXT2WEB_GEMMA_MODEL or gemma-4-26b-a4b-it for gemma')
    parser.add_argument('--url', default='http://127.0.0.1:11434')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--set', choices=['tune', 'holdout'], default='tune')
    parser.add_argument('--output')
    args = parser.parse_args()
    cases = HOLDOUT if args.set == 'holdout' else CASES
    rows = run(args.backend, args.model, args.url, args.timeout, cases)
    positive = [r for r, c in zip(rows, cases) if c[3] is not None]
    negative = [r for r, c in zip(rows, cases) if c[3] is None]
    model_rows = [r for r in rows if r['output_tokens']]
    summary = {'backend': args.backend, 'model': args.model or 'default', 'set': args.set, 'positive_passed': sum(r['passed'] for r in positive), 'positive_total': len(positive),
               'negative_passed': sum(r['passed'] for r in negative), 'negative_total': len(negative),
               'mean_seconds': round(sum(r['seconds'] for r in rows) / len(rows), 2),
               'mean_output_tokens': round(sum(r['output_tokens'] for r in model_rows) / max(len(model_rows), 1), 1),
               'mean_prompt_tokens': round(sum(r['prompt_tokens'] for r in model_rows) / max(len(model_rows), 1), 1),
               'offline_routed': [r['id'] for r in rows if 'offline' in r['routes'] or 'deterministic' in r['routes']]}
    print(json.dumps(summary, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps({'summary': summary, 'cases': rows}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
