"""The native component vocabulary and its validator.

A native widget is a JSON tree of components. Every component has a strict whitelist of
properties, so a generated spec can't smuggle in raw CSS or code: styling is built by the
renderer from these values only, and CSS-like values are checked against SAFE_CSS.
"""

import re

from . import data

# Colors and backgrounds: #hex, rgb()/rgba(), named colors and linear/radial gradients.
# No ';', '{', '}', quotes or url(), so a value can never break out of its CSS declaration.
SAFE_CSS = re.compile(r"^(?!.*url\()[#a-zA-Z0-9(),.%\s-]{1,200}$")
ALIGN = {"start", "center", "end", "fill"}
SHADOWS = {"none", "soft", "medium", "strong"}
WEIGHTS = {"light", "normal", "medium", "semibold", "bold", "heavy"}

# property kinds
COLOR, NUMBER, TEXT, BOOL, COND, INT, ENUM, CHILDREN, ACTION, MARGIN = (
    "color", "number", "text", "bool", "condition", "int", "enum", "children", "action", "margin")

COMMON = {
    "margin": (MARGIN,), "width": (INT,), "height": (INT,),
    "halign": (ENUM, ALIGN), "valign": (ENUM, ALIGN),
    "hexpand": (BOOL,), "vexpand": (BOOL,),
    "visible": (COND,), "tooltip": (TEXT,), "opacity": (NUMBER,),
}
BOX = {
    "children": (CHILDREN,), "spacing": (INT,), "padding": (MARGIN,),
    "background": (COLOR,), "radius": (INT,), "border": (COLOR,), "border_width": (INT,),
    "shadow": (ENUM, SHADOWS),
}
COMPONENTS = {
    "column": BOX,
    "row": BOX,
    "card": BOX,
    "overlay": {"children": (CHILDREN,)},
    "spacer": {"size": (INT,)},
    "label": {
        "text": (TEXT,), "size": (NUMBER,), "weight": (ENUM, WEIGHTS), "color": (COLOR,),
        "align": (ENUM, {"start", "center", "end"}), "font": (TEXT,), "ellipsize": (BOOL,),
        "wrap": (BOOL,), "letter_spacing": (NUMBER,), "text_shadow": (BOOL,),
    },
    "icon": {"name": (TEXT,), "text": (TEXT,), "size": (NUMBER,), "color": (COLOR,)},
    "image": {"src": (TEXT,), "size": (NUMBER,), "radius": (NUMBER,), "fit": (ENUM, {"cover", "contain"})},
    "progress": {
        "value": (NUMBER,), "max": (NUMBER,), "color": (COLOR,), "track": (COLOR,),
        "thickness": (NUMBER,), "radius": (NUMBER,),
    },
    "ring": {
        "value": (NUMBER,), "max": (NUMBER,), "size": (INT,), "thickness": (NUMBER,),
        "color": (COLOR,), "track": (COLOR,), "start": (NUMBER,), "children": (CHILDREN,),
    },
    "sparkline": {
        "value": (NUMBER,), "points": (INT,), "color": (COLOR,), "fill": (COLOR,),
        "min": (NUMBER,), "max": (NUMBER,), "line_width": (NUMBER,),
    },
    "button": {
        "text": (TEXT,), "icon": (TEXT,), "action": (ACTION,), "size": (NUMBER,),
        "color": (COLOR,), "background": (COLOR,), "radius": (INT,),
    },
}
REQUIRED = {"button": ("action",), "progress": ("value",), "ring": ("value",), "sparkline": ("value",),
            "image": ("src",)}
MAX_NODES = 250
MAX_DEPTH = 12


class UISpecError(ValueError):
    pass


def _is_template(value) -> bool:
    return isinstance(value, str) and "{" in value


def _check_choice(value, path, check):
    """A choice list: [{"when": cond, "value": v}, ..., default]."""
    if not value:
        raise UISpecError(f"{path}: an empty choice list")
    for i, item in enumerate(value):
        if isinstance(item, dict):
            if set(item) != {"when", "value"}:
                raise UISpecError(f"{path}[{i}]: choices look like {{\"when\": condition, \"value\": ...}}")
            _check_condition(item["when"], f"{path}[{i}].when")
            check(item["value"], f"{path}[{i}].value")
        else:
            check(item, f"{path}[{i}]")


def _check_condition(value, path):
    if isinstance(value, bool):
        return
    if not isinstance(value, str):
        raise UISpecError(f"{path}: a condition must be a string such as \"{{media.status}} == Playing\"")
    error = data.check_condition(value)
    if error:
        raise UISpecError(f"{path}: {error}")


def _check_value(kind, extra, value, path, commands):
    def again(v, p):
        _check_value(kind, extra, v, p, commands)

    if isinstance(value, list) and kind not in (CHILDREN, MARGIN):
        return _check_choice(value, path, again)
    if kind == COLOR:
        if not isinstance(value, str) or not (_is_template(value) or SAFE_CSS.match(value)):
            raise UISpecError(f"{path}: not a color (use #rrggbb, rgba(...), a gradient or a template)")
    elif kind == NUMBER:
        if not (isinstance(value, (int, float)) and not isinstance(value, bool)) and not _is_template(value):
            raise UISpecError(f"{path}: expected a number or a template like \"{{cpu}}\"")
    elif kind == INT:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4000:
            raise UISpecError(f"{path}: expected a whole number of pixels")
    elif kind == TEXT:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise UISpecError(f"{path}: expected text")
    elif kind == BOOL:
        if not isinstance(value, bool):
            raise UISpecError(f"{path}: expected true or false")
    elif kind == COND:
        _check_condition(value, path)
    elif kind == ENUM:
        if value not in extra:
            raise UISpecError(f"{path}: must be one of {', '.join(sorted(extra))}")
    elif kind == MARGIN:
        ok = (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, list) and 1 <= len(value) <= 4
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value))
        if not ok:
            raise UISpecError(f"{path}: expected pixels, or a list [top, right, bottom, left]")
    elif kind == ACTION:
        if value not in commands:
            raise UISpecError(f"{path}: \"{value}\" is not a declared command")
        if commands[value].get("interval", 0) != 0:
            raise UISpecError(f"{path}: button actions must be declared with \"interval\": 0")


def validate_ui(tree, commands: dict | None = None) -> dict:
    """Validate a native component tree. Raises UISpecError with a precise path."""
    commands = commands or {}
    count = 0

    def walk(node, path, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES:
            raise UISpecError(f"too many components (max {MAX_NODES})")
        if depth > MAX_DEPTH:
            raise UISpecError(f"{path}: nested too deeply")
        if not isinstance(node, dict) or "type" not in node:
            raise UISpecError(f"{path}: each component is an object with a \"type\"")
        kind = node["type"]
        if kind not in COMPONENTS:
            raise UISpecError(f"{path}: unknown component \"{kind}\" (use {', '.join(sorted(COMPONENTS))})")
        allowed = {**COMMON, **COMPONENTS[kind]}
        for key, value in node.items():
            if key == "type":
                continue
            if key not in allowed:
                raise UISpecError(f"{path} ({kind}): unknown property \"{key}\" "
                                  f"(allowed: {', '.join(sorted(allowed))})")
            spec = allowed[key]
            if spec[0] == CHILDREN:
                if not isinstance(value, list):
                    raise UISpecError(f"{path}.{key}: expected a list of components")
                for i, child in enumerate(value):
                    walk(child, f"{path}.{key}[{i}]", depth + 1)
            else:
                _check_value(spec[0], spec[1] if len(spec) > 1 else None, value, f"{path}.{key}", commands)
        for key in REQUIRED.get(kind, ()):
            if key not in node:
                raise UISpecError(f"{path} ({kind}): \"{key}\" is required")
        if kind == "button" and "text" not in node and "icon" not in node:
            raise UISpecError(f"{path} (button): give it a \"text\" or an \"icon\"")

    walk(tree, "ui", 0)
    return tree
