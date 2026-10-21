# Text2Web — controlled-English webpage compiler

The web editor now accepts ordinary English and follow-up edits, with an optional
local Ollama model fallback. See [NLP architecture and setup](docs/NLP_ARCHITECTURE.md)
for the schema, compiler boundaries, model configuration, persistent state and
evaluation details. Offline mode is enabled by default and requires no model API.

Text2Web compiles a controlled-English language into actual `index.html`
and `style.css` files. It has a Lark LALR parser, symbol-table references,
layout-cycle checks, selected accessibility checks, an optimized page-tree IR,
and deterministic code generation. It supports semantic page sections, links,
navigation, images, nested cards/containers, lists, tables, static forms, reusable
styles and responsive layouts. This is not a full English parser or WCAG audit.

See the [expanded language guide](docs/LANGUAGE.md) for supported phrases, property
values, defaults, containment, static-form limitations and the optional NLP adapter.
Complete examples are in `examples/service-landing.sp`, `examples/college-event.sp`,
`examples/personal-portfolio.sp` and `examples/contact-page.sp`.

## Run on this machine

Open PowerShell in the `compiler-project` folder. Use the project-local
environment; no activation is needed:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>, then select **Compile Webpage**. Use **Apply follow-up**
to modify the saved page, or **Open saved page** after an unsuccessful edit.
Stop the server with
Ctrl+C. This is a local development application, not a deployed production service.

To compile the demonstration from the command line:

```powershell
.\.venv\Scripts\python.exe -m text2web examples\fest.sp --output build\fest --debug --force
Start-Process .\build\fest\index.html
```

`--debug` displays normalized input, tokens, the AST, symbol table, and page-tree IR.

Compile the ordinary-English review example using the interpretation pipeline:

```powershell
.\.venv\Scripts\python.exe -m text2web examples\natural-review.sp --natural --output build\natural-review --debug
```

The original CLI mode remains available without `--natural`. The Flask editor
always uses the English interpreter and any configured model fallback. Model
responses are schema-validated operations converted to DSL and passed through
Lark, AST construction, semantic validation, IR, optimization and code generation.

`--force` explicitly replaces generated files in the selected folder; omit it to
protect existing output. The generated files work together in an ordinary browser
without Flask. Buttons have no behavior.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For a fresh environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

`requirements.txt` records supported dependency ranges; `requirements-lock.txt`
records the original dependency versions. The expanded implementation was tested
on Python 3.14. Install `requirements-dev.txt` for HTML/CSS validators and optional
Chrome checks; see [validation results](docs/VALIDATION.md).

## Supported language

The patterns below retain compatibility with existing projects. For all new
components and properties, use the [expanded language guide](docs/LANGUAGE.md).

Start with exactly one page declaration. Put one instruction on each line, or
separate multiple instructions on a line with full stops. Blank lines are allowed
and still count toward source line numbers. A final full stop is optional.
Double-quoted text uses JSON escapes such as `\"`, `\\`, and `\n`; literal
multiline strings are not supported.

```text
Create a page titled "Techno Fest".
Add a big heading that says "Techno 2026".
Add a paragraph that says "Welcome to our college fest".
Add a blue button that says "Register".
Make it bold.
```

| Pattern | Meaning |
| --- | --- |
| `Create a page titled "Title".` | Set the document's browser-tab title |
| `Add a heading that says "Text".` | Add an `h1` |
| `Add a paragraph that says "Text".` | Add a `p` |
| `Add a button that says "Text".` | Add a visual-only `button` |
| `Add an image "stage.png" described as "Main stage".` | Add an image with `src` and accessible `alt` text |
| `Make it bold.` / `Make this bold.` | Set the last introduced element's font weight |
| `Make it Arial.` / `Make it serif.` | Set the last introduced text element's font family |
| `Make it small.` / `Make it red.` | Change the latest element's size or color |
| `Put it to the left of the heading.` | Position the latest element relative to the latest element of the named type |

- `add`, `create`, and `insert` are equivalent after normalization.
- `put`, `place`, and `move` are equivalent for positioning; `over`/`under`
  mean `above`/`below`; `large`/`regular` mean `big`/`medium`.
- Keywords are case-insensitive; quoted text keeps its case, spaces, and punctuation.
- Multiple full-stop-separated instructions may share a source line. Diagnostics
  retain the original line number. `please` can prefix an instruction. `a`, `an`,
  or `the` can precede a page or element.
  `that` before `says` is optional. These words remain grammar tokens rather than
  being removed globally, which avoids changing quoted content.
- Elements optionally accept size **then** color:
  `Insert a small green paragraph that says "Hello".`
- Sizes: `small` = `0.875rem`, `medium` = `1.125rem`, `big` = `2.5rem`.
- Text font families: `Arial`, `serif`, and `sans-serif`.
- Colors: `blue`, `red`, `green`, `black`, `white`.
- Color means text color for headings/paragraphs and background color for buttons.
  Buttons use preset foreground colors. Text contrast is checked against the
  generated background, and combinations below 4.5:1 are compile errors.
- The page declaration is not an eligible reference target. `it`/`this` selects
  the most recently **introduced** element. Position targets select the latest
  element of the named type; supported directions are left, right, above, and below.
- Images require a non-empty description and a relative or HTTP(S) source. Image
  paths used by the command-line compiler are copied from beside the `.sp` file
  into the output folder. The web editor accepts uploaded PNG, JPEG, GIF, or WebP
  files whose names match local image paths. Remote HTTP(S) images need no upload.
- Layout constraints are cycle-checked and emitted as flexbox rows and columns.
  Simple nested row/column layouts are supported; overlapping layouts that cannot
  be represented as simple nesting are rejected with a diagnostic.
- No arbitrary CSS values, comments, JavaScript, or databases are accepted.
  Forms are static inert previews with disabled submit buttons.
  Multiple instructions on one line must be separated by a full stop. Buttons are
  visual only.

The quoted text is preserved in the AST and escaped for HTML. Normal browser
whitespace rules still apply to titles, headings, and buttons; paragraphs use
`white-space: pre-wrap`.

## Compiler design stages

| PDF stage / concept | Implementation |
| --- | --- | --- |
| 1. Input and normalization | Original lines, case folding and synonyms outside quoted text |
| 2. Lexical analysis | Lark token stream with original source line numbers |
| 3. Syntax analysis | LALR grammar, AST, and independent line-based syntax diagnostics |
| 4. Reference resolution | Symbol table resolves `it`/`this` and named element-type targets |
| 5. Layout constraints | Directed row/column constraints, cycle detection, line-aware diagnostics |
| 6. Type/accessibility checks | Element/property compatibility, image descriptions and URL schemes, button names, 4.5:1 text contrast |
| 7. IR and optimization | HTML-independent page tree; redundant wrappers are removed, identical CSS rules are merged, and later property assignments replace earlier values |
| 8. Code generation | Escaped, deterministic HTML and CSS; flexbox rows and columns |
| Error reporting | Syntax, reference, type, layout, and accessibility errors include source lines; any error prevents output |
| Interface | Flask editor, sandboxed preview, file downloads, and inspectors for source, tokens, AST, symbols, and page-tree IR |

Normalization preserves strings, normalizes words and translates documented English
patterns to constrained DSL instructions. **Lark's grammar and LALR parser decide
whether that DSL is syntactically valid**; semantic checks validate types and values.
The parser's structured tree is converted to explicit `Statement` records.
Resolved `Element` records are the symbol table; validated elements and layout
constraints produce a separate page-tree IR used by the generator.

If any sentence has a syntax error, parsing continues at the next full stop, but
semantic resolution and generation are skipped. This prevents an invalid declaration from
silently changing what `it` means. Semantic and accessibility checks collect
independent errors before code generation. Previously successful builds are
retained, but the UI does not show them as the result of a failed attempt.
Disk failures are reported separately; writing two files is not an atomic
filesystem transaction.

## Files created

The compiler is organized into small, independently testable phases.

| Files | Responsibility |
| --- | --- |
| `text2web/__init__.py`, `compiler.py` | Public compiler entry point and phase orchestration |
| `text2web/model.py` | Sentences, AST statements, symbols, diagnostics, result records |
| `text2web/normalizer.py`, `english.py` | Quote-preserving normalization, rule-based English conversion and source line tracking |
| `text2web/grammar.lark`, `parser.py` | Formal grammar, Lark lexer/LALR parser, AST construction |
| `text2web/semantics.py`, `assets.py`, `accessibility.py`, `layout.py` | Page rules, safe references/assets, accessibility checks, constraints, and page-tree optimization |
| `text2web/properties.py` | Shared component/property whitelist and typed value validation |
| `text2web/codegen.py`, `render.py` | Legacy-compatible and expanded semantic rendering, reusable CSS, local image copying, guarded output writing |
| `text2web/__main__.py` | Command-line entry point |
| `app.py`, `templates/index.html`, `static/app.css`, `static/app.js` | Flask editor, inspector, responsive preview, file downloads, writing-guide toggle and line count |
| `examples/fest.sp`, `examples/portfolio.sp`, `examples/complete.sp`, `examples/invalid.sp` | Compiler examples for common, portfolio, image/layout, and failing cases |
| `tests/`, `pytest.ini` | Compiler phases, expanded features, complete pages, HTML/CSS validity, optional browser viewports, CLI and Flask checks |
| `requirements.txt`, `requirements-lock.txt`, `.gitignore` | Dependencies and generated-file exclusions |
| `README.md`, `docs/PROJECT_GUIDE.md`, `docs/VALIDATION.md` | Project instructions, full feature walkthrough, and verification results |

The `.venv` directory contains the local dependencies. Flask saves each successful
compilation under `build/web/<build-id>/`, including any uploaded images. Build
history has no automatic cleanup. Validated compiler state and workspace revisions
are persisted in `build/workspaces.sqlite3`; follow-ups retain existing components,
IDs and images. An opaque browser cookie selects the local workspace.

## Complete project examples and verification

Compile either `examples\fest.sp` or `examples\portfolio.sp` with the command
above. To compile `examples\complete.sp`, put a PNG/JPEG/GIF/WebP `stage.png`
beside the source file; the CLI copies it into the output. In the web editor,
choose matching local image files in **Local images** before compiling.

The project implements the complete compiler workflow described in the course
reference for this controlled-English subset. It is intentionally not a general
English parser: supported wording is documented in the language guide. Layouts
include nested rows/columns, grids and responsive stacking; accessibility covers
selected checks (not a full audit),
and the generated pages have no JavaScript, form submission, or database.
Compiler phases share one entry point between the CLI and Flask editor.

Implementation references: [Lark API](https://lark-parser.readthedocs.io/en/stable/classes.html)
and [Flask testing documentation](https://flask.palletsprojects.com/en/stable/testing/).
