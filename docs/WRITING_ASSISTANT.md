# Writing Assistant

The web editor has a separate **Writing Assistant** panel. It sits between the
editor and preview on wide screens and below the editor on smaller screens.
Suggestions are displayed only in that panel; no menus or completions cover the
textarea and no source is changed automatically.

## Use it

Restart Flask after updating the project, then open http://127.0.0.1:5000.

1. Click inside an instruction in the page editor or follow-up editor.
2. Type normally. After a short pause, the panel shows the current instruction
   and supported wording where a correction is available.
3. Choose **Apply suggestion** to replace only that instruction. Other lines,
   including later instructions, remain unchanged.
4. Or choose an action under **Build an instruction**, fill its fields, and review
   the supported instruction. **Replace instruction** changes the current incomplete
   instruction; **Insert instruction** appends a new instruction to the editor.
5. Select **Compile Webpage** or **Apply follow-up** to validate and generate the
   complete page. Suggestions themselves do not compile files or save revisions.

Actions include page titles, navigation, headings, paragraphs, buttons, images,
cards, a static contact form, background/text colors, rounded corners and mobile
layout. Component choices come from successfully interpreted editor content or
the user's saved page. Color and size options use the compiler's actual whitelist.
The color builder also accepts six-digit hex values.

Example corrections:

| Typed instruction | Suggested supported instruction |
| --- | --- |
| make a webpage named abhi | Create a page titled "abhi". |
| make webpage background colour green | Set the page background-color to "green". |
| make a navigation bar with home,about,contact | Create a navigation bar with "home", "about" and "contact" links. |
| make it yellow, after creating a nav | Set the navigation bar background-color to "yellow". |

Yellow, orange and purple are native compiler color names. Pink can be suggested
as a known hex equivalent. Ambiguous `it`
references are not guessed; the suggestion is disabled and the user can choose
an explicit component in the builder.

Where a transparent navigation bar would fail contrast on a dark page background,
the panel can offer an explicit nav background matching the page. This additional
color appears in the suggested sentence and explanation before the user applies
it. Image builders require real source/description values. Local image presence
is verified during export, not during writing assistance. Forms remain static.

## Validation and behavior

`POST /api/writing-assistant` receives the source, UTF-16 browser cursor position,
editor mode, and optional builder fields. The server uses the compiler's existing
quote-aware instruction segmentation to locate the current instruction. It checks
candidates through `NaturalInterpreter` in offline mode and the existing compiler.
No model calls, generated files or saved-state mutations occur on this endpoint.

Corrections are checked against preceding instructions. Builder insertions are
checked against the complete current content. Later incomplete instructions can
still make an eventual compile fail; the panel explicitly directs users to compile
the full page. Earlier invalid instructions are flagged before downstream edits
are offered as ready. Unsafe values, invalid references, missing fields and
unsupported styles disable the affected action.

The client debounces requests, cancels superseded requests and checks editor/text/
cursor snapshots before applying any response. It supports both editors, quoted
punctuation, same-line sentences, semicolons, line breaks and Unicode characters.
Suggested text is inserted into DOM nodes using `textContent`, never HTML injection.
Input changes during an in-flight request invalidate the old suggestions.

Files:

- `text2web/writing_assistant.py`: catalogue, current-instruction ranges, corrections,
  component targets, template construction and compiler checks.
- `app.py`: read-only JSON endpoint and catalogue supplied to the template.
- `text2web/workspace.py`: explicit SQLite connection closure after reads/transactions,
  including the frequent saved-page lookups used by guidance.
- `templates/index.html`: standalone accessible panel and builder controls.
- `static/writing-assistant.js`: live guidance, fields, explicit apply/insert actions,
  cancellation and stale-response protection.
- `static/app.css`: separate desktop panel and responsive stacking.
- `tests/test_writing_assistant.py`: compiler/API, state isolation, unsafe input,
  current-range and context tests.
- `tests/test_writing_assistant_browser.py`: real typing, clicking, templates,
  saved-page follow-ups, stale updates and mobile/tablet layout.

This is guided English assistance, not unrestricted spelling correction or a model
autocomplete service. Unknown instructions can still require the builder or the
sentence guide. The compiler remains the final authority.

Validation after the layout/language fixes: **360 tests passed, 1 optional
live-model test skipped**, including seven real Chrome assistant tests. Partial
`create` suggestions and the fallback layout without an assistant panel are tested.

If an already-running Flask process serves older HTML, restart `app.py` once.
Workspace responses now disable HTML caching, assets have modification-version
URLs, templates reload, and CSS only reserves a third column when the assistant
panel exists. A cached older template therefore does not leave an empty column.
