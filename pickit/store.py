"""On-disk widget storage: ~/.local/share/pickit/widgets/<id>/{widget.json,index.html}."""

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from . import runtime

DATA_DIR = runtime.DATA_HOME / "pickit"
WIDGETS_DIR = DATA_DIR / "widgets"
# Touched after every change so the desktop daemon (a separate process) can react.
STAMP = DATA_DIR / "changed"


def notify_changed() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STAMP.with_suffix(".tmp")
    tmp.write_text(uuid.uuid4().hex)
    tmp.replace(STAMP)


def signature(manifest: dict) -> str:
    """Identifies a widget's content; ignores position so drags don't trigger reloads."""
    rest = {k: v for k, v in manifest.items() if k not in ("x", "y")}
    h = hashlib.sha256(json.dumps(rest, sort_keys=True).encode())
    try:
        h.update(html_path(manifest["id"]).read_bytes())
    except FileNotFoundError:
        pass
    return h.hexdigest()


def commands_hash(commands: dict) -> str:
    canonical = json.dumps(commands or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def is_approved(manifest: dict) -> bool:
    if not manifest.get("commands"):
        return True
    return manifest.get("approved_hash") == commands_hash(manifest["commands"])


def widget_dir(widget_id: str) -> Path:
    return WIDGETS_DIR / widget_id


def html_path(widget_id: str) -> Path:
    return widget_dir(widget_id) / "index.html"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "widget"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def list_widgets() -> list[dict]:
    if not WIDGETS_DIR.exists():
        return []
    widgets = []
    for d in sorted(WIDGETS_DIR.iterdir()):
        try:
            widgets.append(load(d.name))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return widgets


def load(widget_id: str) -> dict:
    return json.loads((widget_dir(widget_id) / "widget.json").read_text())


def load_html(widget_id: str) -> str:
    return html_path(widget_id).read_text()


def save_manifest(manifest: dict, notify: bool = True) -> None:
    d = widget_dir(manifest["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "widget.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(d / "widget.json")
    if notify:
        notify_changed()


def save_spec(spec: dict, widget_id: str | None = None, approved: bool = False,
              prompt: str | None = None) -> dict:
    """Create or update a widget from a generated spec. Returns the manifest."""
    if widget_id:
        manifest = load(widget_id)
    else:
        manifest = {"id": _slug(spec["name"]), "enabled": True, "history": []}
    manifest.update({
        "name": spec["name"],
        "width": spec["width"],
        "height": spec["height"],
        "position": spec.get("position", "top-right"),
        "commands": spec.get("commands", {}),
    })
    if approved:
        manifest["approved_hash"] = commands_hash(manifest["commands"])
    if prompt:
        manifest.setdefault("history", []).append(prompt)
    d = widget_dir(manifest["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(spec["html"])
    save_manifest(manifest)
    return manifest


def to_spec(manifest: dict) -> dict:
    """The subset of a widget that is round-tripped through the LLM for refinement."""
    return {
        "name": manifest["name"],
        "width": manifest["width"],
        "height": manifest["height"],
        "position": manifest.get("position", "top-right"),
        "commands": manifest.get("commands", {}),
        "html": load_html(manifest["id"]),
    }


def delete(widget_id: str) -> None:
    shutil.rmtree(widget_dir(widget_id), ignore_errors=True)
    notify_changed()


def watch(callback):
    """Call `callback()` on the GTK main loop whenever any widget changes (debounced)."""
    from gi.repository import Gio, GLib
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    monitor = Gio.File.new_for_path(str(DATA_DIR)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
    pending = [0]

    def fire():
        pending[0] = 0
        callback()
        return False

    def on_event(_m, file, other, _event):
        names = {file.get_basename(), other.get_basename() if other else None}
        if STAMP.name in names and not pending[0]:
            pending[0] = GLib.timeout_add(150, fire)

    monitor.connect("changed", on_event)
    return monitor  # caller must keep a reference
