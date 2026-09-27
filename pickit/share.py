"""Widget files (.pickit): export a widget to share it, import one someone else made.

A .pickit file is JSON: {"pickit": 1, "name", "engine", "width", "height", "position",
"commands", "ui" or "html"}. It never carries an approval, a screen position or the
prompt history, and an imported widget is validated exactly like an AI-generated one.
"""

import json
import re
from pathlib import Path

from . import __version__, generator, store

FORMAT = 1
EXTENSION = ".pickit"
MIME_TYPE = "application/x-pickit-widget"
MAX_BYTES = 2 * 1024 * 1024  # widgets are a few KB; HTML ones with embedded images maybe 1 MB


class WidgetFileError(ValueError):
    pass


def default_filename(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "widget") + EXTENSION


def file_data(spec: dict) -> dict:
    """What goes into a .pickit file for a widget spec."""
    keys = ("name", "engine", "width", "height", "position", "commands", "ui", "html")
    return {"pickit": FORMAT, "exported_by": f"Pickit {__version__}", **{k: spec[k] for k in keys if k in spec}}


def export_widget(widget_id: str, path) -> Path:
    path = Path(path)
    text = json.dumps(file_data(store.to_spec(store.load(widget_id))), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text)
    return path


def read_widget_file(path) -> dict:
    """Load and validate a widget file. Returns a spec with no approval; raises WidgetFileError."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise WidgetFileError(f"{path.name} is too large to be a widget ({path.stat().st_size // 1024} KB).")
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError) as e:
        raise WidgetFileError(f"Could not read {path.name}: {e}") from None
    except json.JSONDecodeError as e:
        raise WidgetFileError(f"{path.name} isn't a Pickit widget (invalid JSON: {e}).") from None
    return parse_widget_data(data, path.name)


def parse_widget_data(data, name: str = "The file") -> dict:
    if not isinstance(data, dict) or not ("pickit" in data or "ui" in data or "html" in data):
        raise WidgetFileError(f"{name} isn't a Pickit widget.")
    version = data.get("pickit", FORMAT)
    if not isinstance(version, int) or version > FORMAT:
        raise WidgetFileError(f"{name} was made with a newer version of Pickit. Update Pickit to open it.")
    try:
        return generator.validate(data)
    except generator.SpecError as e:
        raise WidgetFileError(f"{name} isn't a valid Pickit widget: {e}") from None
