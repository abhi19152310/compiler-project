"""The shared property/type whitelist. No user supplied CSS is emitted unchecked."""

import re
from urllib.parse import unquote, urlsplit

from .assets import local_asset_path

COLORS = {
    "dark-green": "#14532d", "dark-blue": "#1e3a8a", "light-blue": "#dbeafe",
    "blue": "#2b6cb0", "red": "#b91c1c", "green": "#166534",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "black": "#111827", "white": "#ffffff", "grey": "#64748b",
    "gray": "#64748b", "light-grey": "#f1f5f9", "light-gray": "#f1f5f9",
}
SIZES = {"small": "0.875rem", "medium": "1.125rem", "big": "2.5rem", "large": "2.5rem"}
CONTAINERS = {"header", "nav", "main", "section", "footer", "aside", "hero", "container", "card",
              "ul", "ol", "li", "table", "tr", "th", "td", "form", "select", "link", "label"}
TYPES = CONTAINERS | {"heading", "paragraph", "button", "image", "input", "textarea", "option", "submit"}
LENGTHS = {"width", "height", "min-width", "min-height", "max-width", "max-height", "margin", "padding",
           "margin-top", "margin-bottom", "margin-left", "margin-right", "padding-top", "padding-bottom",
           "padding-left", "padding-right", "border-radius", "gap", "font-size", "border-width"}
ENUMS = {
    "font-family": {"arial", "serif", "sans-serif", "monospace", "system-ui"},
    "font-weight": {"normal", "bold", "400", "500", "600", "700"},
    "text-align": {"left", "right", "center", "justify"},
    "text-decoration": {"none", "underline", "line-through"},
    "display": {"flex", "grid", "block"}, "flex-direction": {"row", "column"},
    "flex-wrap": {"wrap", "nowrap"}, "align-items": {"start", "end", "center", "stretch", "flex-start", "flex-end"},
    "align-self": {"auto", "start", "end", "center", "stretch"},
    "justify-content": {"start", "end", "center", "space-between", "space-around", "space-evenly"},
    "object-fit": {"contain", "cover", "fill", "none", "scale-down"},
    "border-style": {"solid", "dashed", "dotted", "none"},
    "box-shadow": {"none", "subtle"}, "transition": {"none", "smooth"},
    "responsive": {"true", "false"}, "mobile-stack": {"true", "false"},
    "button-style": {"true", "false"}, "required": {"true", "false"},
    "decorative": {"true", "false"}, "target": {"_blank", "_self"},
    "type": {"text", "email", "password", "checkbox", "radio"},
}
CSS_KEYS = LENGTHS | (set(ENUMS) - {"responsive", "mobile-stack", "button-style", "required", "decorative", "target", "type"}) | {
    "color", "text-color", "background-color", "border-color", "line-height", "columns", "order", "background-image", "size",
    "hover-color", "hover-background-color", "hover-text-decoration",
}
ATTR_KEYS = {"src", "href", "alt", "name", "id", "level", "value", "placeholder", "minlength", "maxlength", "for", "aria-label"}
ALLOWED = CSS_KEYS | set(ENUMS) | ATTR_KEYS


def valid_url(value: str, *, image: bool = False) -> bool:
    try:
        decoded = unquote(value)
        if not value or any(c.isspace() or ord(c) < 32 for c in decoded) or "\\" in decoded:
            return False
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"}:
            # Accessing port validates malformed numeric ports as well.
            return bool(parsed.hostname and not parsed.username and not parsed.password and parsed.port != 0)
        if image:
            local_asset_path(value)
            return True
        return not parsed.scheme and not parsed.netloc and not value.startswith("//") and bool(parsed.path or parsed.fragment)
    except ValueError:
        return False


def color(value: str) -> str:
    return COLORS.get(value, value)


def luminance(value: str) -> float:
    value = color(value)
    channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first: str, second: str) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def readable_foreground(background: str) -> str:
    return max(('white', 'black'), key=lambda candidate: contrast(candidate, background))


def validate_property(kind: str, key: str, value: str) -> str | None:
    if key not in ALLOWED:
        return f'Unsupported property "{key}"; use a documented property.'
    restricted = {
        "src": {"image"}, "alt": {"image"}, "decorative": {"image"}, "object-fit": {"image"},
        "href": {"link"}, "target": {"link"}, "button-style": {"link"}, "level": {"heading"},
        "type": {"input"}, "required": {"input", "select", "textarea"},
        "placeholder": {"input", "textarea"}, "minlength": {"input", "textarea"},
        "maxlength": {"input", "textarea"}, "value": {"input", "option"}, "for": {"label"},
    }
    if key in restricted and kind not in restricted[key]:
        return f'{kind} cannot have the {key} property.'
    if kind == "image" and key in {"font-family", "font-weight", "font-size", "size", "color", "text-color", "text-align", "line-height", "text-decoration"}:
        return f'Images cannot have {key} formatting.'
    if key.startswith("hover-") and kind not in {"link", "button", "submit"}:
        return 'Hover styles are supported on links and buttons.'
    if key in LENGTHS:
        if value == "auto" and key in {"width", "height", "margin", "margin-left", "margin-right"}:
            return None
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|rem|em|%|vw|vh)", value)
        if value != "0" and (not match or float(match[1]) > 10000):
            return f'{key} needs a non-negative dimension (px, rem, em, %, vw or vh), at most 10000.'
        if key in {"width", "height", "font-size"} and (value == "0" or match and float(match[1]) == 0):
            return f'{key} must be greater than zero.'
    elif key in {"color", "text-color", "background-color", "border-color", "hover-color", "hover-background-color"}:
        if value not in COLORS and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return f'{key} needs a supported color name or six-digit hex color.'
    elif key == "hover-text-decoration":
        if value not in ENUMS["text-decoration"]:
            return 'Unsupported hover text decoration.'
    elif key in ENUMS and value not in ENUMS[key]:
        return f'Invalid {key}: {value}. Expected one of: {", ".join(sorted(ENUMS[key]))}.'
    elif key == "size" and value not in SIZES:
        return 'Size must be small, medium or large.'
    elif key == "line-height" and (not re.fullmatch(r"\d+(?:\.\d+)?", value) or not 1 <= float(value) <= 3):
        return 'Line height must be a number between 1 and 3.'
    elif key == "columns" and value not in {str(n) for n in range(1, 13)}:
        return 'Grid columns must be an integer from 1 to 12.'
    elif key == "order" and (not re.fullmatch(r'-?\d{1,3}', value) or not -100 <= int(value) <= 100):
        return 'Flex/grid order must be an integer from -100 to 100.'
    elif key == "level" and value not in {str(n) for n in range(1, 7)}:
        return 'Heading level must be from 1 to 6.'
    elif key in {"minlength", "maxlength"} and (not re.fullmatch(r"\d{1,5}", value) or int(value) > 10000):
        return f'{key} must be an integer from 0 to 10000.'
    elif key == "id" and not re.fullmatch(r"[a-zA-Z][\w-]*", value):
        return 'IDs must start with a letter and contain only letters, digits, underscores or hyphens.'
    elif key == "href" and not valid_url(value):
        return 'Link href must be an HTTP(S) URL without credentials, a page path, or a non-empty fragment.'
    elif key == "src":
        try:
            local_asset_path(value)
        except ValueError:
            return 'Image sources must be a safe relative path or an HTTP(S) URL without credentials.'
    elif key == "background-image":
        if not valid_url(value, image=True) or not value.startswith(("https://", "http://")) or any(c in value for c in '\"\'<>'):
            return 'Background images require an HTTP(S) URL without quotes or angle brackets.'
    elif key in {"name", "for", "aria-label"} and not value.strip():
        return f'{key} cannot be empty.'
    return None
