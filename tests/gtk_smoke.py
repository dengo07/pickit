"""GTK smoke test (run under a display, e.g. `xvfb-run -a python3 tests/gtk_smoke.py`).

Builds every shipped native example as a real desktop widget window and checks that a
native-only desktop never loads WebKit, then checks that the HTML engine still works.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Never touch the real widget store, even inside Flatpak (where XDG_* are ignored).
os.environ["PICKIT_DATA_HOME"] = tempfile.mkdtemp()
os.environ["PICKIT_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("GDK_BACKEND", "x11")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from pickit import daemon, store  # noqa: E402,F401  (the daemon module must not pull in WebKit)
from pickit.widget_window import WidgetWindow  # noqa: E402

for path in sorted((ROOT / "pickit" / "prompts" / "native_examples").glob("*.json")):
    store.save_spec(json.loads(path.read_text()))  # not approved: no commands run in CI
# An invented icon name must not crash GTK (it would fall back to a "missing image" icon).
store.save_spec({"name": "Bad icon", "engine": "native", "width": 100, "height": 40, "commands": {},
                 "ui": {"type": "icon", "name": "no-such-icon-anywhere"}})
windows = [WidgetWindow(m, {}, {}) for m in store.list_widgets()]
for w in windows:
    w.show_all()
loop = GLib.MainLoop()
GLib.timeout_add(1500, loop.quit)
loop.run()
assert all(w.view.get_children() for w in windows), "a native widget rendered nothing"
webkit = [m for m in sys.modules if "WebKit" in m]
assert not webkit, f"native-only desktop loaded WebKit: {webkit}"
print(f"ok: {len(windows)} native widgets (including an unknown icon), WebKit not loaded")

from pickit.html_view import WidgetView  # noqa: E402

view = WidgetView()
view.load_widget("<html><body>hi</body></html>", {}, False)
GLib.timeout_add(1000, loop.quit)
loop.run()
print("ok: HTML engine still works")
for w in windows:
    w.destroy()
Gtk.main_iteration_do(False)

from pickit import app, config  # noqa: E402

dlg = app.SettingsDialog(None, {**config.load(), "ollama_url": "http://127.0.0.1:9"})
for backend_id, *_ in app.BACKENDS:
    dlg.backend.set_active_id(backend_id)
    assert dlg.pages.get_visible_child_name() == backend_id
assert set(dlg.values()) <= set(config.DEFAULTS), "settings dialog writes an unknown config key"
GLib.timeout_add(500, loop.quit)
loop.run()  # the Ollama page's model lookup fails quietly against a closed port
dlg.destroy()
print("ok: settings dialog pages")
