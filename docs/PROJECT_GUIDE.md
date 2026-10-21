# Text2Web project walkthrough

For the natural-language review workflow, local model setup, persistent follow-up
edits and compiler architecture diagram, see [NLP_ARCHITECTURE.md](NLP_ARCHITECTURE.md).
The editor now starts with the ordinary-English `examples/natural-review.sp` demo.

This walkthrough retains the original compiler demonstrations. The expanded
component and CSS language is documented in [LANGUAGE.md](LANGUAGE.md). Try
`examples/service-landing.sp`, `examples/college-event.sp`,
`examples/personal-portfolio.sp` and `examples/contact-page.sp` for complete pages.
The contact example generates a static inert form preview, with no submission,
authentication or storage.

## Run the web editor

From PowerShell in the project folder:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. Compile the college-fest example, inspect the
normalized sentences, tokens, AST, symbol table, and page-tree IR, then open
the generated HTML and CSS. The preview is sandboxed. Buttons are visual only.

## Demonstrate layout and accessibility

1. Compile `examples\complete.sp` in the web editor. Upload `stage.png` when
   prompted. The image is given its description as alternative text and placed
   left of the heading.
2. Change the position sentence to `Put it to the right of the heading.` and
   compile again to see the reversed row order.
3. Add `Put it to the left of the heading.` after that. The conflicting
   constraints are reported with both source lines and no preview is generated.
4. Remove the contradiction, then change the heading instruction to
   `Add a white big heading that says "Techno 2026".` The contrast checker
   reports that the text does not meet 4.5:1.
5. Restore a passing color and compile. The page tree shows the nested layout
   structure; identical CSS rules are combined in the generated stylesheet.

The CLI can copy adjacent local images automatically:

```powershell
.\.venv\Scripts\python.exe -m text2web examples\complete.sp --output build\complete --debug --force
Start-Process .\build\complete\index.html
```

Place a valid PNG, JPEG, GIF, or WebP file named `stage.png` in `examples`
before running that command.

## Other examples and checks

- `examples\fest.sp`: headings, paragraph, button, formatting, and symbol reference
- `examples\portfolio.sp`: styles, vertical position constraints, and a portfolio page
- `examples\invalid.sp`: syntax error and no generated output

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
