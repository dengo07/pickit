"""Which widget commands the user approved: Pickit's own record, kept apart from the widgets.

A widget file only says what it wants to run; it can't approve itself. Approvals live in
~/.config/pickit/approvals.json (mode 0600), per widget id, with the hash of the exact command
set, when and from which Pickit version it was approved, and where the widget came from:

    {"version": 1, "migrated": true,
     "widgets": {"<id>": {"hash", "name", "approved_at", "pickit", "source", "runner"}}}

"runner" is how commands ran when they were approved (sandbox.py). An approval given while
commands ran in the restricted sandbox doesn't carry over to full access: switching to it asks
again. Switching to the sandbox keeps every approval, since commands then get less, not more.

Copying or editing a widget's folder therefore never carries an approval along. This is a
record of consent, not protection against software that already runs as you: such a program
could edit this file too (see SECURITY.md). With the restricted command runner, widget
commands can't reach it, since they don't see the home folder at all.
"""

import contextlib
import datetime
import fcntl
import hashlib
import json
import os

from . import __version__, runtime

SOURCES = ("generated", "gallery", "imported", "edited", "reviewed", "migrated")


def commands_hash(commands: dict) -> str:
    """The exact command set: any change to a command, interval or network flag changes it."""
    canonical = json.dumps(commands or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _dir():
    return runtime.CONFIG_HOME / "pickit"  # looked up each time: tests point it elsewhere


def path():
    return _dir() / "approvals.json"


def _empty() -> dict:
    return {"version": 1, "migrated": False, "widgets": {}}


def _read() -> dict:
    try:
        data = json.loads(path().read_text())
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("widgets"), dict):
        return _empty()
    data["widgets"] = {k: v for k, v in data["widgets"].items()
                       if isinstance(v, dict) and isinstance(v.get("hash"), str)}
    return data


def _write(data: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = path().with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path())


@contextlib.contextmanager
def _editing():
    """Read-modify-write under a lock: the Pickit window and the widget daemon both write."""
    _dir().mkdir(parents=True, exist_ok=True)
    with open(_dir() / "approvals.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read()
        yield data
        _write(data)


def _runner(value):
    from . import sandbox
    m = sandbox.mode(value)
    return value if m == sandbox.CUSTOM else m


def covers(entry: dict, runner) -> bool:
    """Whether an approval still holds with commands running through `runner`."""
    from . import sandbox
    approved_under = entry.get("runner", sandbox.HOST)  # earlier approvals: full access
    current = _runner(runner)
    return current == sandbox.RESTRICTED or current == approved_under


def is_approved(widget_id: str, commands: dict) -> bool:
    if not commands:
        return True
    from . import sandbox
    entry = _read()["widgets"].get(widget_id)
    return bool(entry) and entry["hash"] == commands_hash(commands) and covers(entry, sandbox.current())


def approve(widget_id: str, name: str, commands: dict, source: str = "generated") -> None:
    from . import sandbox
    with _editing() as data:
        data["widgets"][widget_id] = {
            "hash": commands_hash(commands), "name": name,
            "approved_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "pickit": __version__, "source": source if source in SOURCES else "generated",
            "runner": _runner(sandbox.current())}


def revoke(widget_id: str) -> None:
    with _editing() as data:
        data["widgets"].pop(widget_id, None)


def entries() -> dict:
    """Every recorded approval, by widget id."""
    return _read()["widgets"]


def migrated() -> bool:
    return bool(_read().get("migrated"))


def migrate(manifests: list[dict]) -> list[str]:
    """Once: move approvals that Pickit 1.5.1 and earlier stored inside widget.json. Afterwards
    an "approved_hash" in a widget file means nothing. Returns the ids it moved."""
    moved = []
    with _editing() as data:
        if data.get("migrated"):
            return []
        for m in manifests:
            commands = m.get("commands") or {}
            if commands and m.get("approved_hash") == commands_hash(commands):
                data["widgets"].setdefault(m["id"], {
                    "hash": commands_hash(commands), "name": m.get("name", m["id"]),
                    "approved_at": "", "pickit": "1.5.1 or earlier", "source": "migrated"})
                moved.append(m["id"])
        data["migrated"] = True
    return moved
