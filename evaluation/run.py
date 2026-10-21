"""Reproducible development-set comparison; no fabricated live-model metrics.

Run: python -m evaluation.run --repeat 5 --output docs/evaluation-results.json
Add --model only with a configured, running Ollama service.
"""

import argparse
from collections import Counter
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
from statistics import mean
from time import perf_counter

from text2web import compile_source
from text2web.nlp import NaturalInterpreter, interpreter_from_env

ROOT = Path(__file__).resolve().parents[1]


def matches(result, case):
    if not result.page_tree or result.page_tree.title != case.get('title'):
        return False
    expected = case.get('elements', [])
    if len(result.symbols) != len(expected):
        return False
    for actual, wanted in zip(result.symbols, expected):
        if actual.type != wanted['type'] or 'text' in wanted and actual.text != wanted['text']:
            return False
        if any(actual.properties.get(k) != v for k, v in wanted.get('properties', {}).items()):
            return False
    return all(result.page_properties.get(k) == v for k, v in case.get('page_properties', {}).items())


def output_matches(result, case):
    if not result.success or not matches(result, case):
        return False
    class Document(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text, self.tags = [], []
        def handle_data(self, data):
            self.text.append(data)
        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))
    document = Document()
    document.feed(result.html)
    for e in case.get('elements', []):
        if e.get('text') and e['text'] not in document.text:
            return False
        if e['type'] == 'link' and 'href' in e.get('properties', {}) and not any(tag == 'a' and attrs.get('href') == e['properties']['href'] for tag, attrs in document.tags):
            return False
    if case.get('escaped') and ('<script>' in result.html or '&lt;script&gt;' not in result.html):
        return False
    return True


def evaluate(cases, converter=None, repeats=5):
    rows = []
    for case in cases:
        timings = []
        for _ in range(repeats):
            start = perf_counter()
            result = compile_source(case['input'], nlp_converter=converter)
            timings.append((perf_counter() - start) * 1000)
        phases = [d.phase for d in result.diagnostics]
        rejected = bool(case.get('reject'))
        parse_valid = not any(p in {'syntax', 'normalization', 'interpretation', 'clarification', 'unsupported', 'service'} for p in phases)
        rows.append({'id': case['id'], 'negative': rejected,
            'interpreted': parse_valid, 'valid_dsl': parse_valid and bool(result.ast),
            'extraction_correct': matches(result, case) if not rejected else None,
            'compiler_success': result.success, 'output_correct': output_matches(result, case) if not rejected else None,
            'safe_rejection': not result.success and result.html is None if rejected else None,
            'correct_rejection': not result.success and case['reject'] in phases if rejected else None,
            'phases': phases, 'latency_ms': round(mean(timings), 3),
            'routes': dict(Counter(t['route'] for t in result.interpretations))})
    positive = [r for r in rows if not r['negative']]
    negative = [r for r in rows if r['negative']]
    metrics = {}
    for key in ['interpreted', 'valid_dsl', 'extraction_correct', 'compiler_success', 'output_correct']:
        count = sum(bool(row[key]) for row in positive)
        metrics[key] = {'correct': count, 'total': len(positive), 'percent': round(100 * count / len(positive), 2)}
    for key in ['safe_rejection', 'correct_rejection']:
        count = sum(bool(row[key]) for row in negative)
        metrics[key] = {'correct': count, 'total': len(negative), 'percent': round(100 * count / len(negative), 2)}
    metrics['average_latency_ms'] = round(mean(r['latency_ms'] for r in rows), 3)
    return {'metrics': metrics, 'cases': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evaluation-results.json')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error('repeat must be between 1 and 100')
    converter = interpreter_from_env() if args.model else NaturalInterpreter()
    if args.model and converter.provider is None:
        parser.error('--model requires TEXT2WEB_NLP_BACKEND=ollama')
    cases = json.loads((ROOT / 'evaluation/cases.json').read_text(encoding='utf-8'))
    if args.model:
        cases.extend(json.loads((ROOT / 'evaluation/model-cases.json').read_text(encoding='utf-8')))
    report = {'python': platform.python_version(), 'repeats': args.repeat, 'dataset': f'{len(cases)} authored development cases; not an independent benchmark',
              'model': converter.provider.model if converter.provider else 'not configured; no live-model results',
              'legacy': evaluate(cases, repeats=args.repeat), 'hybrid': evaluate(cases, converter, args.repeat)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key]['metrics'] for key in ['legacy', 'hybrid']}, indent=2))


if __name__ == '__main__':
    main()
