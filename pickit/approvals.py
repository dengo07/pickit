"""Which widget commands the user approved: Pickit's own record, kept apart from the widgets.

A widget file only says what it wants to run; it can't approve itself. Approvals live in
~/.config/pickit/approvals.json (mode 0600), per widget id, with the hash of the exact command
set, when and from which Pickit version it was approved, and where the widget came from:

    {"version": 1, "migrated": true,
     "widgets": {"<id>": {"hash", "name", "approved_at", "pickit", "source", "runner"}}}

"runner" is how commands ran when they were approved (sandbox.py). An approval given while
commands ran in the restricted sandbox doesn't carry over to full access: switching to it asks
again. Switching to the sandbox keeps every approval, since commands then get less, not more.
Internet commands in the sandbox normally get a network of their own (pasta); an approval given
without pasta records that they share the host's network, and one given with it doesn't cover
sharing, so removing pasta asks again instead of quietly widening what was approved.

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


def _uses_network(commands) -> bool:
    return any(isinstance(c, dict) and c.get("network") for c in (commands or {}).values())


def _policy(runner, commands=None):
    """sandbox.policy, except that sharing the host's network only matters to a command set
    that uses the internet (`commands` unknown: assume it does)."""
    from . import sandbox
    p = sandbox.policy(runner)
    if p == sandbox.SHARED and commands is not None and not _uses_network(commands):
        return sandbox.RESTRICTED
    return p


def covers(entry: dict, runner, commands=None) -> bool:
    """Whether an approval still holds with commands running through `runner`. From least to
    most access: the sandbox, the sandbox sharing the host's network, full access."""
    from . import sandbox
    approved_under = entry.get("runner", sandbox.HOST)  # earlier approvals: full access
    current = _policy(runner, commands)
    if current == sandbox.RESTRICTED:
        return True
    if current == sandbox.SHARED:
        return approved_under != sandbox.RESTRICTED
    return current == approved_under


def runner_now():
    """How commands run right now, as an approval records it."""
    from . import sandbox
    return sandbox.policy(sandbox.current())


def holds(approved_under, runner=None, commands=None) -> bool:
    """Whether consent given while commands ran through `approved_under` still holds now (or
    with `runner`). The editor and running widgets ask this, not only the saved record."""
    from . import sandbox
    return covers({"runner": approved_under}, sandbox.current() if runner is None else runner, commands)


def is_approved(widget_id: str, commands: dict) -> bool:
    if not commands:
        return True
    from . import sandbox
    entry = _read()["widgets"].get(widget_id)
    return bool(entry) and entry["hash"] == commands_hash(commands) and covers(
        entry, sandbox.current(), commands)


def approve(widget_id: str, name: str, commands: dict, source: str = "generated") -> None:
    from . import sandbox
    with _editing() as data:
        data["widgets"][widget_id] = {
            "hash": commands_hash(commands), "name": name,
            "approved_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "pickit": __version__, "source": source if source in SOURCES else "generated",
            "runner": _policy(sandbox.current(), commands)}


def revoke(widget_id: str) -> None:
    with _editing() as data:
        data["widgets"].pop(widget_id, None)


def entries() -> dict:
    """Every recorded approval, by widget id."""
    return _read()["widgets"]


def migrated() -> bool:
    return bool(_read().get("migrated"))


def migrate(manifests: list[dict]) -> list[str]:
    """Once: retire the approvals that Pickit 1.5.1 and earlier stored inside widget.json.

    That field was an unkeyed hash of the widget's own commands, so anything able to write the
    file could have written it too. It is therefore not taken as consent: those widgets wait
    for a review (right-click → Review commands). Returns the ids that carried the old field."""
    with _editing() as data:
        if data.get("migrated"):
            return []
        data["migrated"] = True
    return [m["id"] for m in manifests if m.get("commands") and m.get("approved_hash")]
