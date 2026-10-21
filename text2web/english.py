"""Rule-based NLP: full-sentence patterns emit DSL, never HTML or unchecked ASTs.

Rules are deliberately explicit. Unmatched/underspecified requests reach the
parser and receive a diagnostic; this layer does not invent page copy.
"""

import json
import re

from .properties import COLORS

Q = r'"(?:[^"\\\r\n]|\\.)*"'
TYPES = r'header|navigation bar|breadcrumb navigation|nav|main(?: content| section)?|section|footer|aside|hero(?: section)?|container|card|heading|paragraph|button|image|link|form|input|textarea|select|label|list item|ordered list|unordered list|table|row|cell'
ALIASES = {"navigation bar": "nav", "breadcrumb navigation": "nav", "main content": "main", "main section": "main",
           "navbar": "nav", "nav bar": "nav", "webpage": "page", "web page": "page", "website": "page",
           "hero section": "hero", "list item": "li", "ordered list": "ol", "unordered list": "ul", "row": "tr", "cell": "td", "submit button": "submit"}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def component(kind, text="", props=None, parent=None):
    output = f'component {quote(kind)} {quote(text)}'
    for key, value in (props or {}).items():
        output += f' with {quote(key)} {quote(str(value))}'
    if parent:
        output += f' inside {quote(parent)}'
    return output


def configure(reference, key, value):
    return f'configure {quote(reference)} {quote(key)} {quote(str(value))}'


def ref(value):
    value = value.strip()
    if re.fullmatch(Q, value):
        return json.loads(value)
    value = re.sub(r'^(?:the|this|a|an)\s+', '', value.lower())
    value = re.sub(r'\s+field$', '', value)
    if value in {"cards", "all cards", "each card"}:
        return "all:card"
    return ALIASES.get(value, value)


def items(value):
    # Splitting is quote-aware: commas and "and" inside a label are content.
    parts = re.split(f'({Q})', value)
    output, pending = [], ""
    for index, part in enumerate(parts):
        if index % 2:
            pending += json.loads(part)
        else:
            fragments = re.split(r'\s*,\s*(?:and\s+)?|\s+and\s+', part, flags=re.I)
            pending += fragments[0]
            for fragment in fragments[1:]:
                if pending.strip():
                    output.append(pending.strip())
                pending = fragment
    if pending.strip():
        output.append(pending.strip())
    return output


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def dimension(value):
    value = value.strip().lower()
    return re.sub(r'\s*(?:pixels?|px)$', 'px', value)


def expand_english(source: str) -> list[str] | None:
    s = re.sub(r'^please\s+', '', source.strip(), flags=re.I).removesuffix('.').strip()
    s = re.sub(r'^(?:create|insert)\b', 'add', s, flags=re.I)
    s = re.sub(r'^(?:place|move)\b', 'put', s, flags=re.I)
    s = re.sub(r'^(?:give)\b', 'give', s, flags=re.I)

    def match(pattern):
        return re.fullmatch(pattern, s, re.I)

    colors = '|'.join(re.escape(k).replace(r'\-', '[- ]') for k in sorted(COLORS, key=len, reverse=True)) + '|#[0-9a-fA-F]{6}'
    if m := match(rf'(?:change|set|make) (?:the )?(?:(.+?)(?:\'s)? )?background(?: colou?r)? (?:to )?({colors})'):
        return [configure(ref(m[1]) if m[1] else 'page', 'background-color', m[2].lower().replace(' ', '-'))]

    # Explicit containment can wrap any supported creation instruction.
    quoted_spans = [(q.start(), q.end()) for q in re.finditer(Q, s)]
    boundaries = [m for m in re.finditer(r' (?:inside|within) ', s, re.I)
                  if not any(start <= m.start() < end for start, end in quoted_spans)]
    if boundaries:
        boundary = boundaries[-1]
        before, after = s[:boundary.start()], s[boundary.end():]
        inner = expand_english(before)
        if inner is None and re.match(r'add\b', before, re.I):
            inner = [before]
        if inner:
            if all(instruction.startswith('component ') for instruction in inner):
                return [instruction + f' inside {quote(ref(after))}' if not re.search(r' inside "(?:[^"\\]|\\.)*"$', instruction) else instruction for instruction in inner]
            return inner + [f'attach "it" {quote(ref(after))}']

    if m := match(rf'add (?:a |an |the )?(?:button-style )?link (?:labelled|labeled|called|that says) ({Q}) (?:that opens|to|pointing to) (.+)'):
        destination = json.loads(m[2]) if re.fullmatch(Q, m[2]) else m[2]
        return [component("link", json.loads(m[1]), {"href": destination, **({"button-style": "true"} if "button-style" in s.lower() else {})})]
    if m := match(r'add a button-style link to the (\w+) page'):
        return [component("link", m[1].capitalize(), {"href": "/" + slug(m[1]), "button-style": "true"})]
    if m := match(r'open (.+?) (?:external )?link in a new tab'):
        return [configure("link" if m[1].lower() in {"this", "the"} else ref(m[1]), "target", "_blank")]
    if m := match(rf'make (.+?) link to (?:the )?(.+)'):
        destination = json.loads(m[2]) if re.fullmatch(Q, m[2]) else m[2]
        destination = "/" if destination.lower() in {"homepage", "home page"} else destination
        # An image becomes a child of a real anchor; other elements must already be links.
        if ref(m[1]) in {"logo", "image"}:
            return [f'wrap {quote(ref(m[1]))} {quote(destination)}']
        return [configure(ref(m[1]), "href", destination)]
    if m := match(rf'add (?:an? )?(?:decorative )?image (?:from |called )?({Q})(?: (?:with (?:the )?description|described as) ({Q}))?'):
        # The original image grammar remains visible in the legacy token stream.
        if re.match(r'add (?:an? )?image "', s, re.I):
            return None
        props = {"src": json.loads(m[1])}
        if "decorative image" in s.lower():
            props["decorative"] = "true"
        return [component("image", json.loads(m[2]) if m[2] else "", props)]
    if m := match(r'display (.+?) at ([-\d.]+) pixels? wide and ([-\d.]+) pixels? tall'):
        return [configure(ref(m[1]), "width", m[2] + "px"), configure(ref(m[1]), "height", m[3] + "px")]
    if m := match(r'make (.+?) responsive(?: and keep its aspect ratio)?'):
        return [configure(ref(m[1]), "responsive", "true")]
    if m := match(r'(?:make|ensure) (.+?) (?:fit inside its card without overflowing|does not overflow its container)'):
        return [configure(ref(m[1]), "max-width", "100%"), configure(ref(m[1]), "object-fit", "contain")]

    if m := match(r'add (?:a )?navigation bar with (.+) links'):
        labels = items(m[1])
        return [component("nav", "", {"aria-label": "Main navigation"})] + [
            component("link", label, {"href": "/" if label.lower() == "home" else "/" + slug(label)}, "nav") for label in labels]
    if match(r'add a header at the top,? (?:the )?main content in the middle and a footer at the bottom'):
        return [component(kind) for kind in ("header", "main", "footer")]
    if m := match(r'add separate sections for (.+)'):
        output = []
        for title in items(m[1]):
            output += [component("section", "", {"name": title, "id": slug(title)}), component("heading", title, {"level": "2"}, title)]
        return output
    if m := match(r'add (?:a )?hero section with (?:a )?heading (' + Q + r'),? (?:a )?description (' + Q + r') and (?:a )?button (' + Q + r')'):
        return [component("hero"), component("heading", json.loads(m[1]), {"level": "1"}, "hero"),
                component("paragraph", json.loads(m[2]), parent="hero"), component("button", json.loads(m[3]), parent="hero")]
    if m := match(rf'add (?:a )?level (\d+) heading (?:that )?says ({Q})'):
        return [component("heading", json.loads(m[2]), {"level": m[1]})]
    if m := match(rf'add (?:a )?heading (?:that )?says ({Q}) at level (\d+)'):
        return [component("heading", json.loads(m[1]), {"level": m[2]})]
    if m := match(rf'add (?:an? |the )?({TYPES})(?: (?:named|called) ({Q}))?'):
        kind = ALIASES.get(m[1].lower(), m[1].lower())
        props = {"name": json.loads(m[2])} if m[2] else {}
        if m[1].lower() == "breadcrumb navigation":
            props["aria-label"] = "Breadcrumb"
        return [component(kind, "", props)]
    if m := match(r'add (?:a )?card (?:with|that has) rounded (?:corners|edges)'):
        return [component("card", "", {"border-radius": "12px"})]
    if m := match(r'add (\w+) cards for (.+)'):
        titles = items(m[2])
        count = NUMBERS.get(m[1].lower(), int(m[1]) if m[1].isdigit() else -1)
        if count != len(titles):
            return None
        output = []
        for title in titles:
            output += [component("card", "", {"name": title}), component("heading", title, {"level": "2"}, title)]
        return output
    if m := match(r'put (?:all )?the cards inside one container'):
        return [component("container", "", {"display": "grid", "columns": "3", "gap": "24px", "mobile-stack": "true"}), 'attach "all:card" "container"']
    if m := match(rf'each card should have (?:a title, )?(?:a )?(?:short )?description ({Q}) and (?:a )?button ({Q})'):
        return [component("paragraph", json.loads(m[1]), parent="all:card"), component("button", json.loads(m[2]), parent="all:card")]
    if m := match(r'put (.+?) (?:inside|in) (.+)'):
        return [f'attach {quote(ref(m[1]))} {quote(ref(m[2]))}']
    if match(r'put the logo on the left and the navigation links on the right'):
        return ['attach "logo" "nav"', configure("nav", "display", "flex"), configure("nav", "justify-content", "space-between"), configure("logo", "margin-right", "auto"), configure("logo", "order", "-1")]
    if m := match(r'put (.+?) (?:to (?:the )?)?(left|right|above|below) (?:of )?(.+)'):
        if ref(m[1]) in {"it", "this"} and ref(m[3]) in {"heading", "paragraph", "button", "image"}:
            return None
        return [f'arrange {quote(ref(m[1]))} {m[2].lower()} {quote(ref(m[3]))}']

    if m := match(r'add (?:an? )?(numbered|ordered|bulleted|unordered) list (?:of|with) (.+)'):
        labels = items(m[2])
        # A topic is not actual list content; do not invent missing items.
        if len(labels) == 1 and not re.fullmatch(Q, m[2]):
            return None
        kind = "ol" if m[1].lower() in {"numbered", "ordered"} else "ul"
        return [component(kind)] + [component("li", label, parent=kind) for label in labels]
    if m := match(rf'add (?:a )?list item (?:that says )?({Q})'):
        return [component("li", json.loads(m[1]))]
    if m := match(r'add (?:a )?table with columns (?:for )?(.+)'):
        return [component("table"), component("tr", parent="table")] + [component("th", label, parent="tr") for label in items(m[1])]
    if m := match(r'add (?:a )?row with (.+)'):
        return [component("tr", parent="table")] + [component("td", label, parent="tr") for label in items(m[1])]

    if m := match(r'add (?:a )?(contact|registration) form with (.+) fields'):
        labels = items(m[2])
        output = [component("form", "", {"name": m[1].lower() + " form"})]
        for label in labels:
            key = label.lower()
            if key not in {"name", "email", "message", "password"}:
                return None
            output.append(component("textarea" if key == "message" else "input", label.capitalize(),
                                    {"name": key, **({"type": key if key in {"email", "password"} else "text"} if key != "message" else {})}, "form"))
        return output + [component("submit", "Submit", parent="form")]
    if m := match(rf'add (?:an? )?(text|email|password|checkbox|radio) (?:input|field|button) (?:labelled|labeled|called) ({Q})'):
        return [component("input", json.loads(m[2]), {"type": m[1].lower()}, "form")]
    if m := match(rf'add (?:a )?(textarea|submit button|label) (?:labelled|labeled|that says) ({Q})'):
        return [component({"submit button": "submit"}.get(m[1].lower(), m[1].lower()), json.loads(m[2]), parent="form")]
    if m := match(rf'add (?:a )?(?:dropdown|select) (?:for selecting|labelled|labeled) (.+?)(?: with options (.+))?'):
        label = json.loads(m[1]) if re.fullmatch(Q, m[1]) else re.sub(r'^a ', '', m[1])
        if not m[2]:
            return None  # Ask for the actual options instead of inventing departments.
        return [component("select", label, parent="form")] + [component("option", item, {"value": item}, "select") for item in items(m[2])]
    if m := match(r'make (.+?) required'):
        return [configure(ref(m[1]), "required", "true")]
    if match(r'put the submit button below the fields'):
        return [configure("form", "display", "flex"), configure("form", "flex-direction", "column")]

    if m := match(r'(?:give|make) (.+?) (?:a corner radius of|rounded (?:corners|edges)(?: of)?) ([-\d.]+) pixels?'):
        return [configure(ref(m[1]), "border-radius", m[2] + "px")]
    if m := match(r'give (.+?) (?:consistent spacing and )?rounded (?:corners|edges)'):
        return [configure(ref(m[1]), "border-radius", "12px")] + ([configure(ref(m[1]), "padding", "24px")] if "consistent spacing" in s.lower() else [])
    if m := match(r'give (.+?) rounded corners, a subtle border and consistent spacing'):
        return [configure(ref(m[1]), key, value) for key, value in {"border-radius": "12px", "border-width": "1px", "border-style": "solid", "border-color": "light-grey", "padding": "24px"}.items()]
    if m := match(r'(?:add|give) a subtle shadow to (.+)'):
        return [configure(ref(m[1]), "box-shadow", "subtle")]
    if m := match(r'give (.+?) ([-\d.]+) pixels? of (padding|margin|gap)'):
        return [configure(ref(m[1]), m[3].lower(), m[2] + "px")]
    if m := match(r'(?:center|centre) (.+?)(?: and align (.+?) to the (left|right))?'):
        output = [configure(ref(m[1]), "text-align", "center")]
        if m[2]:
            output += [configure(ref(m[2]), "display", "block"), configure(ref(m[2]), "margin-" + ("left" if m[3].lower() == "right" else "right"), "auto")]
        return output
    if m := match(r'make (.+?) (?:centered|centred)'):
        return [configure(ref(m[1]), "text-align", "center")]
    if m := match(rf'(?:set|change) ({Q}|[^"\n]+?)(?:\'s)? ([a-z-]+) to ({Q}|[^"\n]+)'):
        value = json.loads(m[3]) if re.fullmatch(Q, m[3]) else dimension(m[3])
        return [configure(ref(m[1]), m[2].lower(), value)]
    if m := match(r'give (.+?) (?:a |an )?(text color|background color|border color|font family|font size|font weight|line height|text alignment|text decoration|minimum width|maximum width|minimum height|maximum height|width|height|padding|margin|gap|border radius|object fit|hover color|hover background color|transition) of (.+)'):
        key = {"text alignment": "text-align", "minimum width": "min-width", "maximum width": "max-width", "minimum height": "min-height", "maximum height": "max-height"}.get(m[2].lower(), m[2].lower().replace(' ', '-'))
        value = json.loads(m[3]) if re.fullmatch(Q, m[3]) else dimension(m[3])
        return [configure(ref(m[1]), key, value)]
    if m := match(r'make (.+?) (?:a )?(flexbox row|flexbox column|grid layout)'):
        return [configure(ref(m[1]), "display", "grid" if m[2].lower() == "grid layout" else "flex")] + ([] if m[2].lower() == "grid layout" else [configure(ref(m[1]), "flex-direction", m[2].lower().split()[-1])])
    if m := match(r'align (.+?) (horizontally|vertically) (?:in the |to the )?(center|left|right|top|bottom)'):
        value = {"left": "start", "right": "end", "top": "start", "bottom": "end"}.get(m[3].lower(), m[3].lower())
        return [configure(ref(m[1]), "display", "flex"), configure(ref(m[1]), "justify-content" if m[2].lower() == "horizontally" else "align-items", value)]
    if m := match(r'make (.+?) wrap'):
        return [configure(ref(m[1]), "display", "flex"), configure(ref(m[1]), "flex-wrap", "wrap")]
    if m := match(r'make (.+?) (bold|small|medium|large|big|blue|red|green|black|white|arial|serif|sans-serif)'):
        if ref(m[1]) in {"it", "this"}:
            return None
        value = m[2].lower()
        key = "font-weight" if value == "bold" else "size" if value in {"small", "medium", "big", "large"} else "font-family" if value in {"arial", "serif", "sans-serif"} else "color"
        return [configure(ref(m[1]), key, value)]
    if m := match(r'display (\w+) cards in a row on desktop'):
        count = NUMBERS.get(m[1].lower(), m[1])
        return [configure("container", "display", "grid"), configure("container", "columns", count)]
    if match(r'stack the cards vertically on mobile'):
        return [configure("container", "mobile-stack", "true")]
    if match(r'make the cards equal in height and align them neatly'):
        return [configure("container", "display", "grid"), configure("container", "align-items", "stretch"), configure("all:card", "height", "100%")]
    if match(r'make the navigation bar adapt to smaller screens'):
        return [configure("nav", "responsive", "true")]
    if match(r'make the layout responsive on mobile devices'):
        return [configure("page", "responsive", "true")]
    if match(r'use a clean, modern design with readable typography'):
        return [configure("page", "font-family", "system-ui"), configure("page", "line-height", "1.6")]
    if m := match(r'use a (\w+) primary color and a ([\w-]+) background'):
        return [configure("all:link", "color", m[1].lower()), configure("page", "background-color", m[2].lower())]
    return None
