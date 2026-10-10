"""Turns a natural-language description into a validated widget spec."""

import json
import re
from pathlib import Path

POSITIONS = {"top-left", "top-center", "top-right", "center-left", "center", "center-right",
             "bottom-left", "bottom-center", "bottom-right"}

from . import store
from .native.spec import UISpecError, validate_ui

PROMPTS = Path(__file__).parent / "prompts"
ENGINES = ("auto", "native", "html")


def _system_prompt() -> str:
    examples = []
    for path in sorted((PROMPTS / "native_examples").glob("*.json")):
        examples.append(f"### {path.stem}\n{json.dumps(json.loads(path.read_text()), ensure_ascii=False)}")
    return (PROMPTS / "system.md").read_text().replace("@@NATIVE_EXAMPLES@@", "\n\n".join(examples))


SYSTEM_PROMPT = _system_prompt()


class SpecError(ValueError):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise SpecError("The response did not contain a JSON object.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise SpecError(f"Invalid JSON: {e}") from e


def validate(spec: dict, engine: str = "auto") -> dict:
    """Check and normalize a generated spec. `engine` other than "auto" is required."""
    if not isinstance(spec, dict):
        raise SpecError("Top-level value must be an object.")
    kind = spec.get("engine") or ("native" if "ui" in spec and "html" not in spec else "html")
    if kind not in ("native", "html"):
        raise SpecError('`engine` must be "native" or "html".')
    if engine in ("native", "html") and kind != engine:
        raise SpecError(f'This widget must use the {engine} engine ("engine": "{engine}").')
    try:
        width = max(80, min(1600, int(spec.get("width", 320))))
        height = max(40, min(1200, int(spec.get("height", 200))))
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON 1e999 is infinity
        raise SpecError("`width` and `height` must be integers.") from None
    position = spec.get("position", "top-right")
    if position not in POSITIONS:
        position = "top-right"
    commands = spec.get("commands") or {}
    if not isinstance(commands, dict):
        raise SpecError("`commands` must be an object.")
    clean = {}
    for key, c in commands.items():
        if isinstance(c, str):
            c = {"cmd": c, "interval": 0}
        if not isinstance(c, dict) or not isinstance(c.get("cmd"), str) or not c["cmd"].strip():
            raise SpecError(f"Command `{key}` must have a non-empty `cmd` string.")
        try:
            interval = float(c.get("interval", 0))
        except (TypeError, ValueError):
            raise SpecError(f"Command `{key}` has a non-numeric interval.") from None
        if 0 < interval < 1:
            interval = 1
        clean[str(key)] = {"cmd": c["cmd"], "interval": interval}
        network = c.get("network", False)
        if not isinstance(network, bool):
            raise SpecError(f"Command `{key}`: `network` must be true or false.")
        if network:  # only when set, so the approval of existing commands stays valid
            clean[str(key)]["network"] = True
    result = {
        "name": str(spec.get("name") or "Widget")[:60],
        "engine": kind,
        "width": width,
        "height": height,
        "position": position,
        "commands": clean,
    }
    if spec.get("expandable") is not None:
        raw = spec["expandable"]
        try:  # generator output is clamped like width/height; shape errors are rejected
            if isinstance(raw, dict) and set(raw) == {"width", "height"}:
                raw = {"width": max(80, min(1600, int(raw["width"]))),
                       "height": max(40, min(1200, int(raw["height"])))}
            result["expandable"] = store.validate_expandable(raw)
        except (TypeError, ValueError, OverflowError) as e:
            raise SpecError(str(e)) from None
    if kind == "native":
        try:
            result["ui"] = validate_ui(spec.get("ui"), clean, result.get("expandable"))
        except UISpecError as e:
            raise SpecError(f"Native `ui` is invalid: {e}") from None
    else:
        html = spec.get("html")
        if not isinstance(html, str) or "<" not in html:
            raise SpecError("`html` must be a non-empty HTML string.")
        result["html"] = html
    return result


def focus_text(focus: dict) -> str:
    """The part of the widget the user selected in the preview, as told to the model."""
    if focus.get("kind") == "native":
        what = (f"the component at {focus['path']}:\n"
                f"{json.dumps(focus['node'], indent=2, ensure_ascii=False)}")
    else:
        what = f"the element `{focus['selector']}`:\n{focus['html']}"
    return (f"SELECTED PART (the user clicked it in the preview): {what}\n"
            "Apply the change request to this part. Keep the rest of the widget as it is, unless the "
            "request can't be done without changing it.")


def generate(backend, prompt: str, current: dict | None = None, engine: str = "auto",
             focus: dict | None = None) -> dict:
    """Ask the backend for a widget. `current` is an existing spec to refine; `focus` is the
    part of it the user selected in the preview (see focus_text)."""
    if engine not in ENGINES:
        engine = "auto"
    if current:
        # Refining with "auto" keeps the widget's engine unless the request asks to switch.
        label = (f"auto (keep {current.get('engine', 'html')} unless the change request asks to switch)"
                 if engine == "auto" else engine)
        selected = f"{focus_text(focus)}\n\n" if focus else ""
        user = (f"Engine: {label}\n\nCURRENT WIDGET JSON:\n{json.dumps(current, indent=2)}\n\n"
                f"{selected}Change request: {prompt}")
    else:
        user = f"Engine: {engine}\n\nCreate this widget: {prompt}"
    messages = [{"role": "user", "content": user}]

    # Repair attempts feed the error back to the model (small local models get two).
    repairs = getattr(backend, "repair_attempts", 1)
    for attempt in range(repairs + 1):
        reply = backend.complete(SYSTEM_PROMPT, messages)
        try:
            return validate(_extract_json(reply), engine)
        except SpecError as e:
            if attempt == repairs:
                raise
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"That output was not usable: {e}\n"
                                            "Reply again with ONLY the complete, valid JSON object."},
            ]
