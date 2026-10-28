# Expanded Text2Web language

The web editor now adds natural-language interpretation with persistent follow-up
edits and a configurable local model. See [NLP_ARCHITECTURE.md](NLP_ARCHITECTURE.md)
for ordinary-English examples, setup and safe reference behavior. This reference
also documents the legacy controlled-language API, whose latest-by-type rules
remain compatible. Natural mode checks ambiguous type references and uses discourse
focus, explicit names, ordinals or directional selectors.

Text2Web uses rule-based English conversion, a Lark LALR grammar, typed AST
statements, a symbol table and a nested page-tree IR. All normalized instructions
pass through parsing and semantic validation. It does not generate arbitrary HTML
or CSS from a prompt. Unsupported or incomplete requests produce source-line
diagnostics and no output.

Start with `Create a page titled "Title".`. Separate instructions with newlines or
full stops. URLs and decimal dimensions do not split sentences. Double-quoted
strings use JSON escapes; single quotes are also accepted as literal delimiters
(use `\'` within them). Quoted content keeps its case and punctuation. Use quotes
for names with punctuation, commas or the word `and`. `Create`, `add`, `insert`
and optional `please` are equivalent. `Place`, `put` and `move` are equivalent.

## References and containment

```text
Create a main named "content".
Create a section named "about" inside "content".
Add a heading that says "About us" inside "about".
Add a paragraph that says "We make useful tools." inside "about".
Give the main section 24 pixels of padding.
```

`it` / `this` means the last introduced element, not the last formatted one.
A type such as `the heading` selects the latest matching type. Quoted names are
case-sensitive; unquoted type words are case-insensitive. Names and HTML IDs must
be unique. Exact text can also identify an element, but duplicate text is ambiguous
and produces an error. Use `Set it name to "unique-name"` to name an existing node.
`all cards` / `each card` selects every card introduced so far.

Use `inside` / `within` on creation or `Put "child" inside "parent"` later.
Containment is explicit: merely creating a section does not capture future lines.
Macro instructions such as navigation, cards and forms create their own children;
an `inside` suffix moves their root components into the specified parent.
Containment cycles, invalid HTML content models and unresolved references fail.
Left/right/above/below positioning relative to another element requires siblings;
these produce flex wrappers and cannot be used for list items, table rows/cells,
options or anchor children. Align one element within its parent using
`Align "name" to the left`, `Align "name" to the center`, or
`Align "name" to the right`. `Put "name" on the left/center/right` is also supported.

## Links, images and dimensions

```text
Create a link labelled 'Visit GitHub' that opens https://github.com.
Open this external link in a new tab.
Create a button-style link to the registration page.
Add an image called 'logo.png' with the description 'Company logo'.
Set it name to "logo".
Display this image at 45 pixels wide and 60 pixels tall.
Make the image responsive and keep its aspect ratio.
Make the logo link to the homepage.
```

Links also accept `labeled`, `called`, `that says`, `to` and `pointing to`.
Anchors always have destinations; buttons provide hover and pressed visual feedback
but do not navigate or perform an action. Use a link or button-style link to navigate.
New-tab anchors get `target="_blank" rel="noopener noreferrer"`.
Destinations can be HTTP(S) URLs without credentials, relative/root page paths,
or fragments. Fragment IDs must exist in the generated page. External pages and
routes are not created or checked for reachability.

Images accept `from`, `called`, `with the description`, or the original
`Add an image "file.png" described as "Description"` syntax. Missing descriptions
are errors, including when only a source was supplied. Explicit `decorative image`
allows an empty alt. `Set the image alt to "Description"` can supply it later.
`Make the image fit inside its card without overflowing` maps to `max-width: 100%`
and `object-fit: contain`. `Set the image object-fit to cover` is also supported.
Positive integer pixel sizes emit HTML width/height attributes plus CSS. Fractional
sizes and other supported units use CSS only. Responsive images retain width and
height attributes for intrinsic ratio while CSS uses `max-width: 100%; height: auto`.

Local images must be safe PNG/JPEG/GIF/WebP paths. Export requires matching files
beside the source, or uploads in the web editor; missing/invalid files stop export.
Remote URLs are syntax-checked but never fetched by the compiler; availability,
image content and remote dimensions are not verified.

## Page structure, navigation and cards

```text
Create a header at the top, the main content in the middle and a footer at the bottom.
Create a navigation bar with Home, About, Services and Contact links inside the header.
Make the navigation bar adapt to smaller screens.
Create a breadcrumb navigation.
Create a link labelled "Home" to "/" inside the nav.
Place the nav above the main.
Create a hero section with a heading "Welcome", a description "Explore our work." and a button "Learn more" inside the main.
Create separate sections for About Us, Our Services and Contact.
Create three cards for Web Development, AI and Cloud Computing.
Each card should have a short description "Tell us about your project." and a button "Learn more".
Put all the cards inside one container.
Give all cards rounded corners, a subtle border and consistent spacing.
Add a subtle shadow to each card.
```

Semantic types include `header`, `nav`, `main`, `section`, `footer`, `aside`, hero
sections, `container` divs and card articles. At most one explicit main is allowed.
When header/footer/main elements are present, the outer page wrapper is a div;
simple legacy documents retain their main wrapper.

The navigation macro maps Home to `/` and other labels to lowercase hyphenated
paths (About Us → `/about-us`). These are navigation destinations, not new pages.
Set each link's `href` explicitly to customize them. Section names receive matching
hyphenated IDs. `Make the logo link to the homepage` wraps the named logo image in
a real anchor. `Put the logo on the left and the navigation links on the right`
moves a named logo into the latest nav and uses flex layout, order -1 and an auto
margin. Linking an existing logo preserves its parent, name and layout settings.

Cards receive actual provided titles; description/button content must be supplied.
Requests for unspecified prose or missing list items return a diagnostic instead
of invented copy. Numbered card creation must match the number of supplied titles.

## Lists, tables and heading levels

```text
Add a numbered list of "Register", "Prepare your portfolio" and "Attend the interview".
Add an unordered list named "technologies".
Add a list item "Frontend" inside "technologies".
Set it name to "frontend".
Add a bulleted list of "HTML", "CSS" and "JavaScript" inside "frontend".
Create a table with columns for Subject, Credits and Grade.
Add a row with "Compilers", "4" and "A".
Add a level 2 heading that says "Details".
Add a heading that says "More details" at level 3.
```

Numbered/ordered produce `ol`, bulleted/unordered produce `ul`, with `li` children.
Nested lists go inside a list item. Tables use rows, column `th scope="col"`
headers and data cells; rows must have matching cell counts. Tables get a scrolling
wrapper for narrow screens. All content is HTML-escaped. A heading defaults to h1
for legacy compatibility; explicit levels are 1–6. Forward level jumps are errors;
the first heading is allowed to start at any level for component snippets.

## Static forms

```text
Create a contact form with name, email and message fields.
Make the email field required.
Add a password field labelled "Password".
Add a checkbox field labelled "Subscribe to updates".
Add a dropdown for selecting a department with options Admissions, Support and Research.
Set the email maxlength to 254.
Set the name placeholder to "Your name".
Place the submit button below the fields.
```

The contact/registration macros accept name, email, message and password fields.
Other controls can be added to an explicit form: text/email/password/checkbox/radio
fields, textareas, selects and submit buttons. `labelled`, `labeled` and `called`
are accepted for input fields. Textareas and submit buttons accept `labelled`,
`labeled` or `that says`. Every control needs non-empty label text; associated
labels are generated automatically. Explicit labels use a `for` reference.

Radio fields require a shared `name` and should have distinct values. Use the DSL
below or `Set it name to "group"` and `Set it value to "choice"` before compilation
finishes. Required, placeholder, minlength and maxlength are validated by type.
Text length constraints must be consistent; dropdown options must be explicit.

Forms are **static, inert previews** with disabled submit buttons and an explanatory
notice. They cannot be filled or submitted until application code connects them.
There is no backend, authentication, email delivery, database or storage. This also
prevents accidental implicit submission of passwords in an exported static page.

## Styling and predictable defaults

Every supported property can be set with either `Set <reference> <property> to
<value>` or `Change <reference> <property> to <value>`. Human-friendly phrases such
as `Give the main section 24 pixels of padding`, `Give the image a width of 45
pixels`, and `Give the heading a font size of 32 pixels` normalize to the same DSL.

| Category | Supported properties / values |
| --- | --- |
| Color | `color`, `text-color`, `background-color`, `border-color`: blue, red, green, yellow, orange, purple, black, white, grey/gray, light-grey/light-gray, or six-digit hex |
| Typography | `font-family`: arial, serif, sans-serif, monospace, system-ui; `font-size`; `font-weight`: normal/bold/400/500/600/700; `text-align`: left/right/center/justify; `line-height`: 1–3; `text-decoration`: none/underline/line-through |
| Dimensions | width/height and min-/max- versions; margin/padding and top/right/bottom/left versions; gap; border-radius; border-width |
| Layout | display: block/flex/grid; flex-direction: row/column; flex-wrap: wrap/nowrap; align-items; align-self; justify-content; columns: 1–12; order: -100–100 |
| Alignment | start/end/center/stretch where applicable; justify-content also space-between/space-around/space-evenly; align-items also flex-start/flex-end |
| Images | object-fit: contain/cover/fill/none/scale-down; background-image: HTTP(S) URL, no local backgrounds |
| Effects | border-style: solid/dashed/dotted/none; box-shadow: subtle/none; transition: smooth/none |
| Interaction | hover-color, hover-background-color, hover-text-decoration on links and buttons |

Dimensions accept non-negative px/rem/em/%/vw/vh, up to 10000; zero is disallowed
for width, height and font-size. Unitless zero is otherwise allowed. `pixels` /
`pixel` normalizes to px. Width also accepts `fit-content`; width, height, margin
and horizontal margins also accept auto. Arbitrary CSS expressions, positioning,
scripts and inline styles are rejected.

| Phrase / token | Exact mapping |
| --- | --- |
| small / medium / large (big) | 0.875rem / 1.125rem / 2.5rem |
| rounded corners / rounded edges | 12px border radius |
| corner radius of 12 pixels | 12px border radius |
| consistent spacing on cards | 24px padding; grouped cards have 24px gap |
| subtle border | 1px solid light-grey |
| subtle shadow | 0 4px 16px rgba(0, 0, 0, 0.08) |
| centered / center the heading | text-align: center |
| modern readable design | system-ui font and line-height: 1.6 |
| smooth transition | color and background-color, 150ms ease; disabled for reduced-motion preferences |
| responsive image | max-width: 100%; height: auto |
| responsive page | below 641px: 24px 16px page padding, container/nav column stacking |

Original `Make it blue` / `Add a blue button` retain their button-background meaning
and select a readable default foreground. `Give the button a text color of white`
uses `text-color` to set its actual foreground independently. On other elements,
color is foreground. Background colors must be paired with readable foregrounds.

```text
Display three cards in a row on desktop.
Stack the cards vertically on mobile.
Make the cards equal in height and align them neatly.
Make the navigation bar adapt to smaller screens.
Make the layout responsive on mobile devices.
```

These refer to the latest container/nav and existing cards. Group cards first.
Grid tracks use `minmax(0, 1fr)` and the mobile breakpoint is 640px. General
`Make the container a flexbox row`, `Make the container a flexbox column`,
`Make the container a grid layout`, `Make the container wrap`, and horizontal/
vertical alignment phrases are supported. Set `columns` explicitly for a grid.

## Canonical DSL and optional NLP adapter

The normalizer emits these grammar productions, also accepted directly:

```text
component "section" "" with "name" "about" with "id" "about"
component "heading" "About us" with "level" "2" inside "about"
configure "about" "padding" "24px"
component "link" "Visit" with "href" "https://example.com" inside "about"
attach "it" "about"
arrange "about" above "footer"
```

`wrap "logo" "/"` wraps a referenced image in a link while retaining its parent
and layout; it is the normalized form of the logo-link phrase.

Component kinds and properties are whitelisted in `text2web/properties.py`.
Additional supported structural kinds are `ul`, `ol`, `li`, `table`, `tr`, `th`,
`td`, `form`, `input`, `textarea`, `select`, `option`, `label`, `submit`.
Attributes include name, id, src, alt, href, target, level, value, placeholder,
required, minlength, maxlength, for and aria-label; applicability is type-checked.
`all:<type>` is a bulk formatting/attachment or parent-copy reference in this DSL.
Repeated property keys in a component declaration are errors. Later configure
statements replace prior assignments; size/font-size aliases use last-write-wins.

Applications may call `compile_source(source, nlp_converter=callable)`. The adapter
is invoked only for an unparsed sentence and returns a DSL string (maximum 32768
characters). Its output goes through normalization, Lark parsing, references,
semantic checks and accessibility checks. Exceptions become diagnostics without
exposing provider details. Original line numbers are retained. The Flask editor
now connects a structured NaturalInterpreter through this hook. Its offline mode
adds compositional extraction, and its configurable Ollama backend makes server-side
model calls. The original callable hook remains available. External adapters remain responsible for
clarification and intent fidelity; syntax validation cannot detect a model changing
the user's meaning. Adapter determinism is not guaranteed by the compiler.

## Output and limits

Expanded components reuse deterministic CSS classes for equivalent property maps
and hover/mobile states. Unused component/layout rules are not emitted. Optimizing
layout wrappers never crosses a semantic parent boundary. Legacy-only programs
retain their original markup and merged ID selectors for compatibility.

Validation covers safe URLs, dimensions, supported nesting, unique IDs/names,
fragment references, labels, link/button names, image descriptions, heading jumps,
and solid foreground/background contrast at 4.5:1 (including hover and inherited
container/page colors). Low contrast is a warning that names the ratio and a
readable color; it does not stop the page from being generated. Contrast over background images is not checked. These are
selected accessibility checks, not WCAG certification. No JavaScript behavior,
unrestricted prose generation, network availability guarantee, backend integration,
or arbitrary CSS is implemented.

See the four complete examples: `college-event.sp`, `personal-portfolio.sp`,
`service-landing.sp` and `contact-page.sp`. Browser tests check all four at 375,
768 and 1440 CSS pixels; this does not guarantee every user-defined layout fits.


### Common English creation and background instructions

The offline English interpreter supports `Make a webpage named abhi.` and
`Make a navbar with Home, About and Contact.` Both `color` and `colour` work
in background instructions, such as `Change the background colour to purple.`
An omitted background target means the page. `Make it yellow.` after creating
navigation changes that navigation's background. Missing page titles, navigation
labels, or background colors request clarification.

Yellow (`#ffff00`), orange (`#ffa500`) and purple (`#800080`) are native named
colors. Buttons, page backgrounds and navigation links choose readable default
foregrounds: dark text for yellow/orange and white text for purple. Explicit text
colors remain subject to the contrast warning. Automatic page text colors update
with later background changes, including saved-page follow-ups.
