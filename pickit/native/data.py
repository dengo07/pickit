"""Data binding for native widgets: command output → values, templates, filters, conditions.

Everything here is a small hand-written interpreter. Widget specs come from an AI, so
nothing is ever passed to `eval`; the worst a hostile template can do is render text.

    "{battery.capacity}%"              → "77%"
    "{cpu|round}"                      → "12"
    "{now|time:%H:%M}"                 → "21:45"
    "{media.status} == Playing"        (condition) → True / False
    [{"when": "{v} < 20", "value": "#f87171"}, "#4ade80"]   (choice) → first match or default
"""

import datetime
import json
import math
import re

MAX_TEMPLATE = 1000
TEMPLATE = re.compile(r"\{([^{}]*)\}")
PATH_ROOT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)")


# --- command output -------------------------------------------------------------
def parse_output(out: str):
    """Turn a command's stdout into data: a JSON value, `key=value` lines, or the text."""
    text = (out or "").strip()
    if text[:1] in ("{", "["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and all("=" in line for line in lines):
        pairs = {}
        for line in lines:
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
        return pairs
    return text


def lookup(data: dict, path: str):
    """`battery.capacity`, `weather.days.0.max` → value, or None when missing."""
    value = data
    for part in path.strip().split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.lstrip("-").isdigit():
            i = int(part)
            value = value[i] if -len(value) <= i < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


def to_number(value):
    """Best-effort number: 77, "77", "77%", "6.2 GB" → float; otherwise None."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", value.replace(",", "."))
        if m:
            return float(m.group(1))
    return None


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(to_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


# --- filters ----------------------------------------------------------------------
def _num(value, default=0.0):
    n = to_number(value)
    return default if n is None else n


def _bytes(value, _arg):
    n = _num(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _duration(value, _arg):
    s = int(_num(value))
    h, rest = divmod(abs(s), 3600)
    m, sec = divmod(rest, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m" if m else f"{sec}s"


def _mmss(value, _arg):
    s = int(_num(value))
    return f"{s // 60}:{s % 60:02d}"


def _time(value, arg):
    fmt = arg or "%H:%M"
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value.strip()):
        try:
            dt = datetime.datetime.fromisoformat(value.strip())
        except ValueError:
            return ""
    else:
        n = to_number(value)
        if n is None:
            return ""
        dt = datetime.datetime.fromtimestamp(n)
    try:
        return dt.strftime(fmt)
    except ValueError:
        return ""


def _round(value, arg):
    n = to_number(value)
    if n is None:
        return value
    digits = int(_num(arg)) if arg else 0
    return round(n, digits) if digits else float(round(n))


FILTERS = {
    "round": _round,
    "int": lambda v, a: float(int(_num(v))),
    "upper": lambda v, a: to_text(v).upper(),
    "lower": lambda v, a: to_text(v).lower(),
    "trim": lambda v, a: to_text(v).strip(),
    "truncate": lambda v, a: (lambda t, n: t if len(t) <= n else t[: max(n - 1, 0)] + "…")(
        to_text(v), int(_num(a, 20))),
    "default": lambda v, a: a if v in (None, "") else v,
    "bytes": _bytes,
    "duration": _duration,
    "mmss": _mmss,
    "time": _time,
    "mul": lambda v, a: _num(v) * _num(a, 1),
    "div": lambda v, a: _num(v) / _num(a, 1) if _num(a, 1) else 0.0,
    "add": lambda v, a: _num(v) + _num(a),
    "sub": lambda v, a: _num(v) - _num(a),
    "percent": lambda v, a: _num(v) * 100,
    "word": lambda v, a: (lambda w, i: w[i] if -len(w) <= i < len(w) else None)(
        to_text(v).split(), int(_num(a, 0))),
    "join": lambda v, a: (a if a is not None else ", ").join(to_text(x) for x in v) if isinstance(v, list)
    else to_text(v),
}


def evaluate_ref(expr: str, data: dict):
    """`path|filter|filter:arg` → value."""
    parts = expr.split("|")
    value = lookup(data, parts[0])
    for f in parts[1:]:
        name, sep, arg = f.strip().partition(":")
        fn = FILTERS.get(name.strip())
        if fn is None:
            continue  # unknown filters are rejected by the validator; be lenient at runtime
        try:
            value = fn(value, arg if sep else None)
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            value = None
    return value


def refs(template) -> set[str]:
    """Root data names a template/condition/choice depends on (for targeted updates)."""
    found: set[str] = set()
    if isinstance(template, str):
        for inner in TEMPLATE.findall(template[:MAX_TEMPLATE]):
            m = PATH_ROOT.match(inner)
            if m:
                found.add(m.group(1))
    elif isinstance(template, list):
        for item in template:
            if isinstance(item, dict):
                found |= refs(item.get("when")) | refs(item.get("value"))
            else:
                found |= refs(item)
    return found


def interpolate(template: str, data: dict):
    """Fill in `{...}` references. A template that is exactly one reference keeps its type."""
    template = template[:MAX_TEMPLATE]
    whole = TEMPLATE.fullmatch(template.strip())
    if whole:
        return evaluate_ref(whole.group(1), data)
    return TEMPLATE.sub(lambda m: to_text(evaluate_ref(m.group(1), data)), template)


# --- conditions ---------------------------------------------------------------------
TOKEN = re.compile(r"""\s*(?:
    (?P<ref>\{[^{}]*\})
  | (?P<str>'[^']*'|"[^"]*")
  | (?P<num>-?\d+(?:\.\d+)?%?)
  | (?P<op>==|!=|<=|>=|<|>|\(|\))
  | (?P<word>[^\s(){}'"=!<>]+)
)""", re.VERBOSE)


def _tokens(expr: str, data: dict):
    out, pos = [], 0
    expr = expr[:MAX_TEMPLATE]
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            if expr[pos:].strip() == "":
                break
            raise ValueError(f"bad condition near {expr[pos:pos + 12]!r}")
        pos = m.end()
        if m.group("ref"):
            out.append(("val", evaluate_ref(m.group("ref")[1:-1], data)))
        elif m.group("str"):
            out.append(("val", m.group("str")[1:-1]))
        elif m.group("num"):
            out.append(("val", to_number(m.group("num"))))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        else:
            word = m.group("word")
            out.append(("op", word) if word in ("and", "or", "not") else ("val", word))
    return out


def truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off", "none", "null")
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


PURE_NUMBER = re.compile(r"\s*-?\d+(?:[.,]\d+)?\s*%?\s*")


def _pure_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and PURE_NUMBER.fullmatch(value):
        return to_number(value)
    return None


def _compare(a, op, b) -> bool:
    if op in ("==", "!="):
        na, nb = _pure_number(a), _pure_number(b)
    else:  # ordering also accepts values that merely start with a number, e.g. "6.2 GB"
        na, nb = to_number(a), to_number(b)
    if na is not None and nb is not None:
        a, b = na, nb
    else:
        a, b = to_text(a).strip().lower(), to_text(b).strip().lower()
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        value = self.or_()
        if self.i != len(self.t):
            raise ValueError("unexpected token in condition")
        return value

    def or_(self):
        value = self.and_()
        while self.peek() == ("op", "or"):
            self.take()
            right = self.and_()
            value = value or right
        return value

    def and_(self):
        value = self.not_()
        while self.peek() == ("op", "and"):
            self.take()
            right = self.not_()
            value = value and right
        return value

    def not_(self):
        if self.peek() == ("op", "not"):
            self.take()
            return not self.not_()
        return self.cmp()

    def cmp(self):
        left = self.atom()
        kind, op = self.peek()
        if kind == "op" and op in ("==", "!=", "<", "<=", ">", ">="):
            self.take()
            return _compare(left, op, self.atom())
        return truthy(left)

    def atom(self):
        kind, value = self.take()
        if kind == "op" and value == "(":
            inner = self.or_()
            if self.take() != ("op", ")"):
                raise ValueError("missing ) in condition")
            return inner
        if kind != "val":
            raise ValueError("expected a value in condition")
        return value


def condition(expr, data: dict) -> bool:
    """Evaluate a condition such as `{media.status} == Playing and {battery.capacity} < 20`."""
    if isinstance(expr, bool):
        return expr
    if not isinstance(expr, str):
        return truthy(expr)
    try:
        return bool(_Parser(_tokens(expr, data)).parse())
    except (ValueError, IndexError, TypeError):
        return False


def check_condition(expr: str) -> str | None:
    """Syntax check for the validator: returns an error message, or None if it parses."""
    try:
        _Parser(_tokens(expr, {})).parse()
    except (ValueError, IndexError, TypeError) as e:
        return str(e)
    return None


# --- property values ------------------------------------------------------------------
def resolve(value, data: dict):
    """A property's value: literal, template string, or choice list (first matching `when`)."""
    if isinstance(value, str):
        return interpolate(value, data) if "{" in value else value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and "when" in item:
                if condition(item["when"], data):
                    return resolve(item.get("value"), data)
            else:
                return resolve(item, data)
        return None
    return value
