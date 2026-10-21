Current follow-up validation: **360 passed, 1 optional live-model test skipped**.
This covers native make-webpage/navbar phrases, background color/colour variants,
yellow/orange/purple in both renderers, readable automatic text colors across saved
follow-ups, partial-create live suggestions, versioned assets, and the layout
fallback when an older template lacks the assistant. Tests ran in real Chrome
where browser interaction was required.

# Project validation

## Writing Assistant: latest results

The separate Writing Assistant enhancement completed with **338 passed, 1 skipped
in 19.47 seconds** on 2026-10-21. The skipped test is still the optional real-model
test. Writing assistance runs entirely offline and does not require that model.

The 58 added checks comprise 52 Python/compiler/API tests and six Chrome interaction
and viewport tests. They verify the real four-line Abhi request can be corrected
one instruction at a time, surrounding text is preserved, page and follow-up editors
stay separate, templates produce valid compiler inputs, custom hex colors work,
missing image fields and unsafe values disable insertion, ambiguous targets are not
guessed, and stale suggestions cannot overwrite newer text. Unicode cursor offsets,
quoted punctuation, semicolons, preceding-context focus and duplicate page titles
are covered. API tests confirm no model calls, output writes or saved revisions
occur while requesting guidance. Layout checks cover 375, 768, 1200 and 1440px.

SQLite connections now close explicitly after workspace reads and transactions,
including frequent reads for follow-up suggestions. Existing persistence and
revision tests continue to pass. A real UI screenshot is available locally at
`build/writing-assistant.png`; setup and behavior are documented in
[WRITING_ASSISTANT.md](WRITING_ASSISTANT.md).

## NLP-assisted enhancement: latest results

Baseline before this enhancement: **220 passed**. The final enhanced suite on
2026-10-21 completed with **280 passed, 1 skipped in 8.70 seconds**. The skipped
test requires a real configured Ollama model; no running Ollama service was
available. All original tests still pass. In addition to the 12 original Chrome
viewport checks, a real Flask/Chrome workflow test verifies English creation,
follow-up edits, nav styling, rounded buttons, stable IDs, mobile editor overflow,
failed edits and saved-state recovery.

New tests verify structured model requests/responses, schema rejection, semantic
and parser boundaries, unsafe URLs/text, model timeout/rate-limit/unavailability,
offline operation during model outages, unique/pronoun/ordinal/directional
references, SQLite persistence, optimistic revisions and image reuse. Controlled
provider responses test integration behavior; they are not real-model accuracy
results. See [architecture and setup](NLP_ARCHITECTURE.md).

The authored 30-case development evaluation (five repetitions per case) produced:

| Metric | Legacy deterministic path | Hybrid offline path |
| --- | --- | --- |
| Successful interpretation, positive cases | 6/24 (25%) | 24/24 (100%) |
| Valid parsed DSL, positive cases | 6/24 (25%) | 24/24 (100%) |
| Expected intent/properties in IR | 6/24 (25%) | 24/24 (100%) |
| Compiler validation, positive cases | 6/24 (25%) | 24/24 (100%) |
| Expected generated HTML/CSS structure | 6/24 (25%) | 24/24 (100%) |
| No output for negative cases | 5/6 | 6/6 |
| Expected rejection diagnostic | 1/6 | 6/6 |
| Mean in-process request latency | 0.427 ms | 1.135 ms |

These are measured development-set results, not independent general-language or
live-model benchmarks. The compiler tests ran concurrently with this timing run;
the timings are illustrative and not isolated performance measurements. Dataset,
metric definitions and per-case traces are in `evaluation/` and
[evaluation-results.json](evaluation-results.json). The hybrid results above used
offline interpretation, with no live model calls. Real-model challenges and an
explicit opt-in test are supplied but have not been executed against a real model.

The ordinary-English demo was exported to `build/natural-review/`, including
`compiler-debug.json` with normalized instructions, lexer tokens, AST, symbols,
interpretation routes and page-tree IR. Existing static-form and accessibility
scope limits still apply.

## Automated tests

Run from the project folder:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

The first component expansion started from 59 tests. The expanded suite includes compiler,
security, HTML/CSS parsing, full-page exports and browser viewport checks.
Install validation dependencies with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:TEXT2WEB_BROWSER = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Without `TEXT2WEB_BROWSER`, the 12 browser tests are skipped explicitly. HTML/CSS
validator tests require html5lib and tinycss2 from requirements-dev.txt and are
skipped if those optional packages are absent.

The 2026-10-21 validation uses Python 3.14, Flask 3.1.3, Lark 1.3.1, pytest 9.1.1,
html5lib 1.1, tinycss2 1.5.1 and Playwright 1.64.0 with installed Chrome
154.0.8037.100. The earlier component-expansion run completed with **220 passed in 7.67 seconds**
(208 non-browser tests and 12 real Chrome tests; none skipped).
The Chrome checks passed at 375, 768 and 1440 CSS pixels for each of the four
new example pages. Checks include page overflow, mobile card stacking, desktop
equal-height rows, navigation direction, image loading/containment, a single main
landmark, and inert forms with disabled submission.

Tests cover normalization and
same-line sentence recovery, Lark parsing, symbol references, type and
accessibility errors, contrast checks, cycle detection, nested row/column IR,
optimization, escaped HTML, local image copying and uploads, CLI behavior,
Flask preview/downloads, and failed-build handling. Expanded tests also cover URL
and CSS injection attempts, missing image descriptions, actual link destinations,
form labels/options and types, heading hierarchy, parent-child cycles and content
models, shared CSS classes, alias precedence, malformed quoted literals, optional
NLP re-parsing, fragment references, inherited/hover contrast, and deterministic
complete-page export. Strict html5lib parsing and tinycss2 parsing are exercised on
all four examples. These parsers check syntax; semantic constraints are also
checked separately by the compiler tests.

All four examples were also exported to `build/examples/` with HTML/CSS and
required local image assets: college event (30 elements), personal portfolio
(19), service landing (27), and contact page (12).

## Manual checks

- The web editor returns a successful page and compiles the built-in fest example.
- The compiler generates deterministic HTML and CSS from the same source.
- The CLI refuses to write failed builds and protects existing output unless
  `--force` is provided.
- The compiler rejects missing image descriptions, invalid image sources,
  unsupported formatting, insufficient text contrast, and contradictory
  position constraints before generating HTML.
- Image uploads accept PNG, JPEG, GIF, and WebP content only; local image URLs
  are copied into the generated folder.

## Scope

These checks cover the documented controlled-English language and its compiler
workflow. They do not claim that Text2Web understands unrestricted English,
implements every WCAG requirement, or provides JavaScript, form submission,
database features, or production hosting.
