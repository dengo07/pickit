"""JS <-> Python bridge: exposes `window.widget` and runs approved shell commands."""

import subprocess
import threading
from pathlib import Path

try:
    from gi.repository import GLib
except ImportError:  # BRIDGE_JS and the expand helpers are pure; only CommandRunner needs GLib
    GLib = None

from . import runtime, sandbox

COMMAND_TIMEOUT = sandbox.TIMEOUT
MAX_OUTPUT = 256 * 1024

BRIDGE_JS = r"""
(() => {
  const handlers = {}, last = {};
  const post = (msg) => window.webkit.messageHandlers.widget.postMessage(JSON.stringify(msg));
  window.widget = {
    on(key, fn) {
      (handlers[key] = handlers[key] || []).push(fn);
      if (key in last) { try { fn(last[key].out, last[key]); } catch (e) { console.error(e); } }
    },
    run(key) { post({type: "run", key}); },
    drag(ev) { post({type: "drag", button: ev ? ev.button : 0}); },
    // Ask the host to expand or collapse the window. The page never says a size: the host
    // uses the manifest's `expandable` size and ignores the request if there is none.
    expand() { post({type: "expand", action: "expand"}); },
    collapse() { post({type: "expand", action: "collapse"}); },
    toggle() { post({type: "expand", action: "toggle"}); },
    expanded: false,
    theme: {},   // the widget theme's colors, radius and font; also CSS variables --pickit-*
    _theme(t) { this.theme = t; window.dispatchEvent(new CustomEvent("pickit-theme", {detail: t})); },
    _expanded(on) {
      this.expanded = on === true;
      document.documentElement.dataset.pickitExpanded = this.expanded ? "true" : "false";
      window.dispatchEvent(new CustomEvent("pickit-expand", {detail: {expanded: this.expanded}}));
    },
    _deliver(key, res) {
      last[key] = res;
      for (const fn of handlers[key] || []) { try { fn(res.out, res); } catch (e) { console.error(e); } }
    },
  };
  window.addEventListener("mousedown", (ev) => {
    if (ev.target.closest && ev.target.closest("[data-drag]")) window.widget.drag(ev);
  });
})();
"""


EXPAND_MS = 220  # animation length, and the shortest time between two accepted requests
EXPAND_ACTIONS = ("expand", "collapse", "toggle")


def parse_expand_message(msg) -> str | None:
    """The action of an untrusted {"type": "expand", "action": ...} message, or None.
    Only the three literal words pass; nothing else from the page is read."""
    if isinstance(msg, dict) and msg.get("type") == "expand":
        action = msg.get("action")
        if isinstance(action, str) and action in EXPAND_ACTIONS:
            return action
    return None


def expand_target(action: str, current: bool) -> bool:
    """The state an action asks for."""
    return (not current) if action == "toggle" else action == "expand"


class ExpandLimiter:
    """At most one accepted request per EXPAND_MS. Requests inside the window are dropped
    (the caller may keep the last one and retry), so a page can't resize in a loop.
    `now` is in milliseconds."""

    def __init__(self, interval_ms: int = EXPAND_MS):
        self.interval = interval_ms
        self._last: float | None = None

    def allow(self, now: float) -> bool:
        if self._last is not None and now - self._last < self.interval:
            return False
        self._last = now
        return True


class CommandRunner:
    """Runs a widget's declared commands on their intervals.

    `deliver(key, result)` is invoked on the GTK main thread with
    result = {"out": str, "err": str, "code": int}.
    """

    def __init__(self, commands: dict, deliver):
        self.commands = commands or {}
        self.deliver = deliver
        self._running: set[str] = set()
        self._timers: list[int] = []
        self._stopped = False

    def start(self):
        # Only periodic commands run automatically. Interval-0 commands are actions
        # (play/pause, next...) and must run only when the widget asks for them.
        for key, c in self.commands.items():
            if c.get("interval", 0) > 0:
                self.run(key)
                ms = int(c["interval"] * 1000)
                self._timers.append(GLib.timeout_add(ms, self._tick, key))

    def refresh(self, max_interval: float | None = None):
        """Re-run periodic commands now (never on-demand actions such as play/pause).

        `max_interval` limits it to fast-changing data, e.g. skip a weather fetch that
        normally runs every 30 minutes when only the battery changed.
        """
        for key, c in self.commands.items():
            interval = c.get("interval", 0)
            if interval > 0 and (max_interval is None or interval <= max_interval):
                self.run(key)

    def _tick(self, key):
        if self._stopped:
            return False
        self.run(key)
        return True

    def run(self, key: str):
        if self._stopped or key not in self.commands or key in self._running:
            return
        self._running.add(key)
        threading.Thread(target=self._exec, args=(key,), daemon=True).start()

    def _exec(self, key):
        command = self.commands[key]
        # Through the configured runner (full access, restricted sandbox or your own wrapper).
        # `timeout` runs on the host side too, so a hung command is killed even when it was
        # started through flatpak-spawn.
        argv = runtime.host_argv(sandbox.argv(command["cmd"], bool(command.get("network")),
                                              sandbox.current()))
        try:
            p = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                               timeout=COMMAND_TIMEOUT + 5, cwd=str(Path.home()),
                               env=runtime.host_env(), stdin=subprocess.DEVNULL)
            result = {"out": p.stdout[:MAX_OUTPUT].strip(), "err": p.stderr[:4096].strip(),
                      "code": p.returncode}
            if p.returncode == sandbox.FAILED and result["err"].startswith("pickit:"):
                print(result["err"].splitlines()[0], flush=True)  # the runner refused: in daemon.log
        except subprocess.TimeoutExpired:
            result = {"out": "", "err": f"timed out after {COMMAND_TIMEOUT}s", "code": -1}
        except OSError as e:
            result = {"out": "", "err": str(e), "code": -1}
        GLib.idle_add(self._finish, key, result)

    def _finish(self, key, result):
        self._running.discard(key)
        if not self._stopped:
            self.deliver(key, result)
        return False

    def stop(self):
        self._stopped = True
        for t in self._timers:
            GLib.source_remove(t)
        self._timers.clear()
