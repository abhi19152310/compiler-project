"""Explicit opt-in test against a real model, never replaced with a fake result."""

import json
import os
from pathlib import Path

import pytest

from evaluation.run import matches, output_matches
from text2web import compile_source
from text2web.nlp import interpreter_from_env


@pytest.mark.skipif(os.environ.get('TEXT2WEB_TEST_LIVE_MODEL') != '1', reason='A running Ollama model is required; set TEXT2WEB_TEST_LIVE_MODEL=1 to validate real model interpretations.')
def test_live_model_challenge_cases():
    converter = interpreter_from_env()
    assert converter.provider is not None, 'Configure TEXT2WEB_NLP_BACKEND=ollama first.'
    cases = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/model-cases.json').read_text(encoding='utf-8'))
    for case in cases:
        result = compile_source(case['input'], nlp_converter=converter)
        if 'reject' in case:
            assert not result.success and any(d.phase == case['reject'] for d in result.diagnostics), (case['id'], result.diagnostics)
        else:
            assert matches(result, case) and output_matches(result, case), (case['id'], result.diagnostics)
            assert any(t['route'] == 'model' for t in result.interpretations), case['id']
