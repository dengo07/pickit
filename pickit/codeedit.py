"""Editing a widget as code: split a spec into editable text, join it back with validation,
and map component paths to their place in the JSON text. No GTK, so it's unit-testable.
"""

import json
import re

from . import generator

SETTINGS_KEYS = ("name", "width", "height", "position", "commands")


class CodeError(ValueError):
    """`tab` is "layout" or "settings"; `span` is the (start, end) offset of the problem, if known."""

    def __init__(self, message: str, tab: str, span: tuple[int, int] | None = None):
        super().__init__(message)
        self.tab, self.span = tab, span


def split_spec(spec: dict) -> tuple[str, str]:
    """(settings JSON, layout text): the layout is the ui JSON or the HTML page."""
    settings = json.dumps({k: spec[k] for k in SETTINGS_KEYS if k in spec}, indent=2, ensure_ascii=False)
    layout = json.dumps(spec["ui"], indent=2, ensure_ascii=False) if spec["engine"] == "native" else spec["html"]
    return settings, layout


def _loads(text: str, tab: str, what: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise CodeError(f"{what}, line {e.lineno}, column {e.colno}: {e.msg}", tab, (e.pos, e.pos + 1)) from None


def join_spec(settings_text: str, layout_text: str, engine: str) -> dict:
    """The validated spec from edited text. Raises CodeError pointing at the problem."""
    settings = _loads(settings_text, "settings", "Settings & commands")
    if not isinstance(settings, dict):
        raise CodeError("Settings & commands must be a JSON object { … }.", "settings", (0, 1))
    candidate = {k: settings[k] for k in SETTINGS_KEYS if k in settings}
    candidate["engine"] = engine
    if engine == "native":
        candidate["ui"] = _loads(layout_text, "layout", "Layout")
    else:
        candidate["html"] = layout_text
    try:
        return generator.validate(candidate, engine)
    except generator.SpecError as e:
        message = str(e).removeprefix("Native `ui` is invalid: ")
        if engine == "native" and message.startswith("ui"):
            raise CodeError(f"Layout: {message}", "layout", _error_span(layout_text, message)) from None
        raise CodeError(f"Settings & commands: {message}", "settings") from None


def _error_span(text: str, message: str) -> tuple[int, int] | None:
    """Where a validator error points: the property if one is named, else the component."""
    path = error_path(message)
    if path is None:
        return None
    spans = json_spans(text)
    if path in spans and (m := re.search(r'(?:unknown property|"(\w+)" is required)\s*"?(\w*)', message)):
        key = m.group(2) or m.group(1)
        if key and (path + (key,)) in spans:  # from the key's quote to the end of its value
            start, end = spans[path + (key,)]
            quote = text.rfind(f'"{key}"', spans[path][0], start)
            return (quote if quote >= 0 else start), end
    return spans.get(path)


# --- component paths ------------------------------------------------------------------------
def node_path(tree, target) -> tuple | None:
    """Path of the `target` dict (by identity) inside `tree`: ("children", 0, "children", 2)."""
    if tree is target:
        return ()
    if isinstance(tree, dict):
        for i, child in enumerate(tree.get("children") or []):
            found = node_path(child, target)
            if found is not None:
                return ("children", i, *found)
    return None


def node_at(tree, path: tuple):
    for part in path:
        tree = tree[part]
    return tree


def path_label(path: tuple) -> str:
    """("children", 0, "color") -> "ui.children[0].color", the validator's notation."""
    out = "ui"
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def error_path(message: str) -> tuple | None:
    """The path at the start of a validator message: "ui.children[1] (label): …" -> ("children", 1)."""
    m = re.match(r"ui((?:\.[A-Za-z_]+|\[\d+\])*)", message)
    if not m:
        return None
    parts = re.findall(r"\.[A-Za-z_]+|\[\d+\]", m.group(1))
    return tuple(int(p[1:-1]) if p.startswith("[") else p[1:] for p in parts)


def describe(node: dict) -> str:
    """A short human name for a component: 'label “{now|time:%H:%M}”', 'ring', 'card'."""
    kind = node.get("type", "component")
    hint = next((node[k] for k in ("text", "name", "icon", "action", "value", "src")
                 if isinstance(node.get(k), str) and node[k]), None)
    if isinstance(hint, str) and hint:
        return f"{kind} “{hint if len(hint) <= 32 else hint[:31] + '…'}”"
    return kind


def find_element(page: str, outer_html: str) -> tuple[int, int] | None:
    """Where an element (as the browser serialized it) starts in the page source: matched on its
    tag and id or first class, since the browser normalizes quotes and attribute order."""
    m = re.match(r"<([A-Za-z][\w-]*)([^>]*)>?", outer_html or "")
    if not m:
        return None
    tag, attrs = m.group(1), m.group(2)
    ident = re.search(r'\bid="([^"]+)"', attrs)
    cls = re.search(r'\bclass="([^"]+)"', attrs)
    if ident:
        pattern = rf"""<{tag}\b[^>]*\bid\s*=\s*["']?{re.escape(ident.group(1))}\b"""
    elif cls and cls.group(1).split():
        pattern = rf"""<{tag}\b[^>]*\bclass\s*=\s*["'][^"']*\b{re.escape(cls.group(1).split()[0])}\b"""
    else:
        pattern = rf"<{tag}\b"
    found = re.search(pattern, page, re.IGNORECASE)
    if not found:
        return None
    end = page.find(">", found.start())
    return found.start(), (end + 1 if end >= 0 else found.end())


# --- positions in JSON text ---------------------------------------------------------------------
_WS = re.compile(r"[ \t\n\r]*")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)
_SCALAR = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null")


def json_spans(text: str) -> dict[tuple, tuple[int, int]]:
    """{path: (start, end)} for every value in a JSON document. Empty if the text isn't valid JSON."""
    spans: dict[tuple, tuple[int, int]] = {}

    def ws(i):
        return _WS.match(text, i).end()

    def value(i, path):
        i = ws(i)
        start, ch = i, text[i]
        if ch == "{":
            i = ws(i + 1)
            if text[i] == "}":
                i += 1
            else:
                while True:
                    m = _STRING.match(text, ws(i))
                    key = json.loads(m.group())
                    i = ws(m.end())
                    assert text[i] == ":"
                    i = ws(value(i + 1, (*path, key)))
                    if text[i] == ",":
                        i += 1
                        continue
                    assert text[i] == "}"
                    i += 1
                    break
        elif ch == "[":
            i, n = ws(i + 1), 0
            if text[i] == "]":
                i += 1
            else:
                while True:
                    i = ws(value(i, (*path, n)))
                    n += 1
                    if text[i] == ",":
                        i += 1
                        continue
                    assert text[i] == "]"
                    i += 1
                    break
        elif ch == '"':
            i = _STRING.match(text, i).end()
        else:
            m = _SCALAR.match(text, i)
            assert m and m.end() > i
            i = m.end()
        spans[path] = (start, i)
        return i

    try:
        value(0, ())
    except (AssertionError, AttributeError, IndexError, ValueError):
        return {}
    return spans
