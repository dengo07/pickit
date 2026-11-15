"""JS <-> Python bridge: exposes `window.widget` and runs approved shell commands."""

import subprocess
import threading
from pathlib import Path

try:
    from gi.repository import GLib
except ImportError:  # BRIDGE_JS and the expand helpers are pure; only CommandRunner needs GLib
    GLib = None

from . import approvals, runtime, sandbox

COMMAND_TIMEOUT = sandbox.TIMEOUT
MAX_OUTPUT = 256 * 1024
MAX_ERROR = 4096

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


def _capture(argv: list[str], env: dict, timeout: float, max_out: int = MAX_OUTPUT,
             max_err: int = MAX_ERROR) -> tuple[str, str, int]:
    """Run `argv` and return (stdout, stderr, exit code), keeping at most `max_out`/`max_err`
    bytes while it runs: whatever a command prints beyond that is read and thrown away, so a
    command can't make Pickit hold its whole output in memory."""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         cwd=str(Path.home()), env=env)
    kept = {"out": bytearray(), "err": bytearray()}

    def drain(stream, name, limit):
        buf = kept[name]
        try:
            while chunk := stream.read1(65536):
                if len(buf) < limit:
                    buf += chunk[:limit - len(buf)]
        except (OSError, ValueError):
            pass  # closed under us after a timeout

    readers = [threading.Thread(target=drain, args=(p.stdout, "out", max_out), daemon=True),
               threading.Thread(target=drain, args=(p.stderr, "err", max_err), daemon=True)]
    for t in readers:
        t.start()
    try:
        code = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        raise
    finally:
        for t in readers:
            t.join(timeout=2)  # a grandchild may still hold the pipe; don't wait for it
        p.stdout.close()
        p.stderr.close()
    return (bytes(kept["out"]).decode(errors="replace"), bytes(kept["err"]).decode(errors="replace"), code)


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
        # Whoever starts a runner has checked the approval for how commands run right now.
        # If that changes to something the approval doesn't cover, nothing more runs here.
        self._approved_under = approvals.runner_now()

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
        runner = sandbox.current()
        if not approvals.holds(self._approved_under, runner, self.commands):
            result = {"out": "", "code": sandbox.FAILED,
                      "err": "pickit: how commands run has changed; approve this widget's commands again"}
            GLib.idle_add(self._finish, key, result)
            return
        # Sharing the host's network (no pasta) only when that is what was approved; the
        # runner script refuses otherwise, whatever this process believes about pasta.
        share = sandbox.policy(runner) == sandbox.SHARED
        argv = runtime.host_argv(sandbox.argv(command["cmd"], bool(command.get("network")), runner, share))
        try:
            out, err, code = _capture(argv, runtime.command_env(), COMMAND_TIMEOUT + 5)
            result = {"out": out.strip(), "err": err.strip(), "code": code}
            if code == sandbox.FAILED and result["err"].startswith("pickit:"):
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
