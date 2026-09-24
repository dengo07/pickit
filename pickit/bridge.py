"""JS <-> Python bridge: exposes `window.widget` and runs approved shell commands."""

import subprocess
import threading
from pathlib import Path

from gi.repository import GLib

from . import runtime

COMMAND_TIMEOUT = 20
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
        for key, c in self.commands.items():
            self.run(key)
            if c.get("interval", 0) > 0:
                ms = int(c["interval"] * 1000)
                self._timers.append(GLib.timeout_add(ms, self._tick, key))

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
        cmd = self.commands[key]["cmd"]
        # `timeout` runs on the host side too, so a hung command is killed even when it
        # was started through flatpak-spawn.
        argv = runtime.host_argv(["timeout", "-k", "2", str(COMMAND_TIMEOUT), "bash", "-c", cmd])
        try:
            p = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                               timeout=COMMAND_TIMEOUT + 5, cwd=str(Path.home()),
                               env=runtime.host_env(), stdin=subprocess.DEVNULL)
            result = {"out": p.stdout[:MAX_OUTPUT].strip(), "err": p.stderr[:4096].strip(),
                      "code": p.returncode}
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
