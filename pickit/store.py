"""On-disk widget storage: ~/.local/share/pickit/widgets/<id>/{widget.json,index.html}."""

import datetime
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from . import approvals, runtime

DATA_DIR = runtime.DATA_HOME / "pickit"
WIDGETS_DIR = DATA_DIR / "widgets"
# Touched after every change so the desktop daemon (a separate process) can react.
STAMP = DATA_DIR / "changed"
VERSIONS_KEPT = 10  # earlier versions of each widget, for Undo in the editor


def notify_changed() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STAMP.with_suffix(".tmp")
    tmp.write_text(uuid.uuid4().hex)
    tmp.replace(STAMP)


# Changed without reloading the widget: position, and the lock / click-through switches.
LIVE_FIELDS = ("x", "y", "locked", "click_through")


def signature(manifest: dict) -> str:
    """Identifies a widget's content; ignores LIVE_FIELDS so a drag or a lock doesn't reload it.
    Includes whether its commands are approved, which lives outside the widget's files."""
    rest = {k: v for k, v in manifest.items() if k not in LIVE_FIELDS}
    rest["approved"] = is_approved(manifest)
    h = hashlib.sha256(json.dumps(rest, sort_keys=True).encode())
    for path in (html_path(manifest["id"]), ui_path(manifest["id"])):
        try:
            h.update(path.read_bytes())
        except FileNotFoundError:
            pass
    return h.hexdigest()


commands_hash = approvals.commands_hash
_migration_checked = False


def _migrate_approvals() -> None:
    """Once per install: approvals from widget.json (1.5.1 and earlier) move to approvals.py's
    record, and the old field is removed. After that, widget files can't approve themselves."""
    global _migration_checked
    if _migration_checked:
        return
    _migration_checked = True
    if approvals.migrated():
        return
    manifests = list_widgets()
    approvals.migrate(manifests)
    for m in manifests:
        if m.pop("approved_hash", None) is not None:
            save_manifest(m, notify=False)


def is_approved(manifest: dict) -> bool:
    """Whether the user approved exactly this widget's current commands. Never decided by the
    widget file itself."""
    _migrate_approvals()
    return approvals.is_approved(manifest["id"], manifest.get("commands") or {})


def approve(manifest: dict, source: str = "reviewed") -> None:
    approvals.approve(manifest["id"], manifest.get("name", manifest["id"]), manifest.get("commands") or {}, source)
    notify_changed()  # approvals live outside the widget folder, so tell the daemon


def revoke(widget_id: str) -> None:
    approvals.revoke(widget_id)
    notify_changed()


def widget_dir(widget_id: str) -> Path:
    return WIDGETS_DIR / widget_id


def html_path(widget_id: str) -> Path:
    return widget_dir(widget_id) / "index.html"


def ui_path(widget_id: str) -> Path:
    """The component tree of a native-engine widget."""
    return widget_dir(widget_id) / "ui.json"


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


def load_ui(widget_id: str) -> dict:
    return json.loads(ui_path(widget_id).read_text())


def save_manifest(manifest: dict, notify: bool = True) -> None:
    d = widget_dir(manifest["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "widget.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(d / "widget.json")
    if notify:
        notify_changed()


def save_spec(spec: dict, widget_id: str | None = None, approved: bool = False,
              prompt: str | None = None, source: str = "generated") -> dict:
    """Create or update a widget from a generated spec. Returns the manifest.
    Updating keeps the previous version (see versions()). `approved` records the user's
    approval of its commands; `source` says where the widget came from (approvals.SOURCES)."""
    if widget_id:
        manifest = load(widget_id)
        previous = to_spec(manifest)
        if _content(previous) != _content(spec):
            _save_version(widget_id, previous, (manifest.get("history") or [None])[-1])
    else:
        manifest = {"id": _slug(spec["name"]), "enabled": True, "history": []}
    engine = "native" if spec.get("engine") == "native" else "html"
    manifest.update({
        "name": spec["name"],
        "engine": engine,
        "width": spec["width"],
        "height": spec["height"],
        "position": spec.get("position", "top-right"),
        "commands": spec.get("commands", {}),
    })
    manifest.pop("approved_hash", None)  # never trusted from the file (see is_approved)
    if approved:
        approvals.approve(manifest["id"], manifest["name"], manifest["commands"], source)
    if prompt:
        manifest.setdefault("history", []).append(prompt)
    d = widget_dir(manifest["id"])
    d.mkdir(parents=True, exist_ok=True)
    # Exactly one content file, so a widget converted between engines leaves nothing stale.
    if engine == "native":
        ui_path(manifest["id"]).write_text(json.dumps(spec["ui"], indent=2))
        html_path(manifest["id"]).unlink(missing_ok=True)
    else:
        html_path(manifest["id"]).write_text(spec["html"])
        ui_path(manifest["id"]).unlink(missing_ok=True)
    save_manifest(manifest)
    return manifest


def to_spec(manifest: dict) -> dict:
    """The subset of a widget that is round-tripped through the LLM for refinement."""
    spec = {
        "name": manifest["name"],
        "engine": "native" if manifest.get("engine") == "native" else "html",
        "width": manifest["width"],
        "height": manifest["height"],
        "position": manifest.get("position", "top-right"),
        "commands": manifest.get("commands", {}),
    }
    if spec["engine"] == "native":
        spec["ui"] = load_ui(manifest["id"])
    else:
        spec["html"] = load_html(manifest["id"])
    return spec


# Where a new widget goes if its preferred corner is taken: corners first, then edges.
ANCHOR_ORDER = ("top-right", "top-left", "bottom-right", "bottom-left", "center-right", "center-left",
                "top-center", "bottom-center")


def free_anchor(preferred: str) -> str:
    """`preferred`, unless a visible, never-moved widget already sits there; then the next free spot."""
    taken = {m.get("position") for m in list_widgets() if m.get("enabled", True) and "x" not in m}
    for anchor in (preferred, *ANCHOR_ORDER):
        if anchor not in taken:
            return anchor
    return preferred


def _content(spec: dict) -> str:
    keys = ("name", "engine", "width", "height", "position", "commands", "ui", "html")
    return json.dumps({k: spec.get(k) for k in keys}, sort_keys=True)


def versions_dir(widget_id: str) -> Path:
    return widget_dir(widget_id) / "versions"


def _save_version(widget_id: str, spec: dict, label: str | None) -> None:
    d = versions_dir(widget_id)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    entry = {"saved": now.isoformat(timespec="seconds"), "label": label or "", "spec": spec}
    (d / f"{now.strftime('%Y%m%dT%H%M%S%f')}.json").write_text(json.dumps(entry))
    for old in sorted(d.glob("*.json"))[:-VERSIONS_KEPT]:
        old.unlink()


def versions(widget_id: str) -> list[dict]:
    """Earlier versions of a widget, oldest first: [{"saved", "label", "spec"}]."""
    out = []
    for path in sorted(versions_dir(widget_id).glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def delete(widget_id: str) -> None:
    shutil.rmtree(widget_dir(widget_id), ignore_errors=True)
    approvals.revoke(widget_id)
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
