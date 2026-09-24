"""Turns a natural-language description into a validated widget spec."""

import json
import re
from pathlib import Path

POSITIONS = {"top-left", "top-center", "top-right", "center-left", "center", "center-right",
             "bottom-left", "bottom-center", "bottom-right"}

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()


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


def validate(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("Top-level value must be an object.")
    html = spec.get("html")
    if not isinstance(html, str) or "<" not in html:
        raise SpecError("`html` must be a non-empty HTML string.")
    try:
        width = max(80, min(1600, int(spec.get("width", 320))))
        height = max(40, min(1200, int(spec.get("height", 200))))
    except (TypeError, ValueError):
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
    return {
        "name": str(spec.get("name") or "Widget")[:60],
        "width": width,
        "height": height,
        "position": position,
        "commands": clean,
        "html": html,
    }


def generate(backend, prompt: str, current: dict | None = None) -> dict:
    """Ask the backend for a widget. `current` is an existing spec to refine."""
    if current:
        user = (f"CURRENT WIDGET JSON:\n{json.dumps(current, indent=2)}\n\n"
                f"Change request: {prompt}")
    else:
        user = f"Create this widget: {prompt}"
    messages = [{"role": "user", "content": user}]

    reply = backend.complete(SYSTEM_PROMPT, messages)
    try:
        return validate(_extract_json(reply))
    except SpecError as e:
        # One repair attempt with the error fed back to the model.
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That output was not usable: {e}\n"
                                        "Reply again with ONLY the complete, valid JSON object."},
        ]
        return validate(_extract_json(backend.complete(SYSTEM_PROMPT, messages)))
