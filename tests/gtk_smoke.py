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

# HTML widgets get the theme as CSS variables, and follow changes live.
from pickit import theme as _theme  # noqa: E402

page = "<html><body><div id=d style='color: var(--pickit-accent)'>x</div></body></html>"
view.load_widget(page, {}, False)
GLib.timeout_add(800, loop.quit)
loop.run()
colors = []


def read_color():
    def done(v, result):
        colors.append(v.evaluate_javascript_finish(result).to_string())
        loop.quit()
    view.evaluate_javascript("getComputedStyle(document.getElementById('d')).color", -1, None, None, None, done)
    loop.run()


read_color()
view.set_theme(_theme.tokens({"preset": "graphite"}))
GLib.timeout_add(300, loop.quit)
loop.run()
read_color()
assert colors == ["rgb(240, 166, 74)", "rgb(91, 155, 213)"], colors
print("ok: HTML widgets get the theme as CSS variables, live")

# Widget scripts can't read local files, send data anywhere, navigate away or read other
# widgets' storage. A local server counts every request that gets out.
import http.server  # noqa: E402
import threading  # noqa: E402

hits = []


class Counter(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    do_POST = do_GET

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Counter)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}"
secret = Path(tempfile.mkdtemp()) / "secret.txt"
secret.write_text("TOPSECRET")


def evaluate(v, code):
    out = []

    def done(view_, result):
        out.append(view_.evaluate_javascript_finish(result).to_string())
        loop.quit()
    v.evaluate_javascript(code, -1, None, None, None, done)
    loop.run()
    return out[0]


attack = f"""<html><body><script>
window.r = {{}};
fetch("{secret.as_uri()}").then(x => x.text()).then(t => r.fetch = t, () => r.fetch = "blocked");
try {{ const x = new XMLHttpRequest(); x.open("GET", "{secret.as_uri()}", false); x.send();
      r.xhr = x.responseText; }} catch (e) {{ r.xhr = "blocked"; }}
fetch("{url}/fetch", {{mode: "no-cors"}}).catch(() => {{}});
new Image().src = "{url}/image";
navigator.sendBeacon("{url}/beacon", "TOPSECRET");
localStorage.setItem("mine", "TOPSECRET");
</script></body></html>"""
view.load_widget(attack, {}, False, host="attacker")
GLib.timeout_add(1200, loop.quit)
loop.run()
result = evaluate(view, "JSON.stringify(r)")
assert "TOPSECRET" not in result, f"a widget read a local file: {result}"
evaluate(view, f"location.href = '{url}/navigate'; window.open('{url}/popup'); 1")
GLib.timeout_add(500, loop.quit)
loop.run()
assert view.get_uri().startswith("pickit-widget://attacker/"), view.get_uri()
other = WidgetView()
other.load_widget("<html><body><script>window.v = String(localStorage.getItem('mine'))</script></body></html>",
                  {}, False, host="other")
GLib.timeout_add(800, loop.quit)
loop.run()
assert evaluate(other, "window.v") == "null", "a widget read another widget's localStorage"
server.shutdown()
assert not hits, f"a widget page sent requests: {hits}"
print("ok: widget pages can't read files, send data, navigate away or read other widgets' storage")
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

# Nothing from a .pickit file opens until the user trusts it; an HTML widget asks even
# without commands, since it contains JavaScript.
from types import SimpleNamespace  # noqa: E402


class Opened(Exception):
    pass


def opens(spec, untrusted, answer):
    asked = []

    def ask(*_a, **_kw):
        asked.append(True)
        return answer
    app.confirm, app.approval_dialog = ask, ask
    maker = SimpleNamespace(busy=False, _can_drop_code_edits=lambda: True)
    maker.present = lambda: (_ for _ in ()).throw(Opened())  # past the trust check
    try:
        app.MakerWindow.open_spec(maker, dict(spec), "test", "test", untrusted=untrusted)
    except Opened:
        return True, bool(asked)
    return False, bool(asked)


real_confirm, real_approval = app.confirm, app.approval_dialog
html_spec = {"name": "H", "engine": "html", "html": "<p>x</p>", "commands": {}, "position": "center"}
native_spec = {"name": "N", "engine": "native", "ui": {"type": "label", "text": "x"}, "commands": {},
               "position": "center"}
with_commands = {**native_spec, "commands": {"c": {"cmd": "echo 1", "interval": 5}}}
assert opens(html_spec, True, False) == (False, True), "an untrusted HTML widget opened without asking"
assert opens(html_spec, True, True) == (True, True)
assert opens(native_spec, True, False) == (True, False), "a native file without commands has nothing to ask"
assert opens(with_commands, True, False) == (False, True), "rejecting a file's commands must cancel it"
assert opens(html_spec, False, False) == (True, False), "gallery widgets must not ask"
app.confirm, app.approval_dialog = real_confirm, real_approval
print("ok: imported files open only when trusted")

from pickit import gallery  # noqa: E402
from pickit.gallery_ui import GalleryWindow  # noqa: E402


class FakeMaker(Gtk.Window):
    def choose_import(self): ...
    def open_spec(self, *a, **kw): ...
    def add_from_gallery(self, *a, **kw): return False


gallery_window = GalleryWindow(FakeMaker())
GLib.timeout_add(800, loop.quit)
loop.run()
assert len(gallery_window.views) == len(gallery.items())
gallery_window.destroy()
print(f"ok: gallery window with {len(gallery.items())} previews")

import cairo  # noqa: E402

from pickit.native import draw  # noqa: E402

surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 20)
draw.sparkline(cairo.Context(surface), 60, 20, [5.0], 0, 10, (1, 1, 1, 1), None, 2)
assert any(surface.get_data()), "a sparkline with one value should draw a flat line"
print("ok: single-value sparkline draws")

# "Select part": hit-testing finds the innermost component under the pointer.
from pickit.native.render import NativeView  # noqa: E402

ui = {"type": "card", "children": [{"type": "label", "text": "a", "size": 30},
                                   {"type": "row", "children": [{"type": "ring", "value": 40, "size": 80}]}]}
host = Gtk.OffscreenWindow()
view = NativeView()
host.add(view)
view.load_widget(ui, {}, False)
host.show_all()
GLib.timeout_add(300, loop.quit)
loop.run()
picked = []
view.set_select_mode(picked.append)
ring = ui["children"][1]["children"][0]
x, y, w, h = view._rect(ring)
assert view.node_at(x + w / 2, y + 4) is ring, "clicking a ring selects the ring"
lx, ly, lw, lh = view._rect(ui["children"][0])
assert view.node_at(lx + lw / 2, ly + lh / 2) is ui["children"][0]
view.set_select_mode(None)
host.destroy()
print("ok: select part finds the component under the pointer")

# The code editor: highlighting and undo/redo.
from pickit.code_view import CodeView  # noqa: E402

editor = CodeView("json")
editor.set_code('{"a": 1}')
editor.get_buffer().insert(editor.get_buffer().get_end_iter(), " ")
editor.undo()
assert editor.get_code() == '{"a": 1}'
editor.redo()
assert editor.get_code() == '{"a": 1} '
print("ok: code editor undo/redo")

# Rings and bars ease to new values, only while animations are enabled.
import time  # noqa: E402

host = Gtk.OffscreenWindow()
view = NativeView()
host.add(view)
view.load_widget({"type": "ring", "value": "{v}", "size": 80}, {}, False)
host.show_all()
view._deliver("v", {"out": "20", "code": 0})
GLib.timeout_add(200, loop.quit)
loop.run()
area = [w for w, n in view._nodes if n["type"] == "ring"][0]
settings = Gtk.Settings.get_default()
settings.props.gtk_enable_animations = True
view._deliver("v", {"out": "80", "code": 0})
Gtk.main_iteration_do(False)
assert area.tween.target == 0.8 and area.tween.shown < 0.8, "the ring should start moving, not jump"
end = time.monotonic() + 1.5
while area.tween.tick and time.monotonic() < end:
    Gtk.main_iteration_do(False)
assert abs(area.tween.shown - 0.8) < 1e-6, f"the ring should end at its value, not {area.tween.shown}"
settings.props.gtk_enable_animations = False
view._deliver("v", {"out": "30", "code": 0})
assert area.tween.shown == 0.3, "with animations off, values jump"
settings.props.gtk_enable_animations = True
host.destroy()
print("ok: rings ease to new values, and jump when animations are off")

# Locked widgets don't move; the menu offers lock, click-through and (with 2+ monitors) monitors.
locked = store.save_spec({"name": "Locked", "engine": "native", "width": 100, "height": 40, "commands": {},
                          "ui": {"type": "label", "text": "locked"}})
locked["locked"] = True
store.save_manifest(locked)
lw = WidgetWindow(locked, {}, {})
lw.show_all()
Gtk.main_iteration_do(False)
lw._begin_drag()
assert lw._drag is None, "a locked widget must not start a drag"
lw.update_flags({**locked, "locked": False, "click_through": True})
assert not lw.locked() and lw.manifest["click_through"]
labels = [i.get_label() for i in lw._menu().get_children() if isinstance(i, Gtk.MenuItem)]
assert "Lock position" in labels and "Click-through" in labels, labels
lw.destroy()
print("ok: lock and click-through")

# Themes: themed widgets follow the theme's card and text; older widgets keep their look.
from pickit import theme  # noqa: E402


def card_css(view):
    return repr(view._styles)  # the rules Pickit generates, before GTK normalizes them


host = Gtk.OffscreenWindow()
view = NativeView()
host.add(view)
host.show_all()
paper = theme.tokens({"preset": "paper", "mode": "light", "radius": 6})
view.set_theme(paper)
themed_ui = {"type": "card", "children": [{"type": "label", "text": "x", "color": "{theme.accent}"}]}
view.load_widget(themed_ui, {}, False)
css = card_css(view)
assert "rgba(252,249,242,0.92)" in css and "'border-radius': '6px'" in css and paper["accent"] in css, css
view.load_widget({"type": "card", "children": [{"type": "label", "text": "x", "color": "#ffffff"}]}, {}, False)
css = card_css(view)
assert "rgba(18,18,24,0.78)" in css and "rgba(252,249,242" not in css, "legacy widgets keep their card"
host.destroy()
print("ok: themed widgets follow the theme; legacy widgets keep their look")

# The property inspector builds editors for every kind of component.
from pickit import gallery as gallery_mod  # noqa: E402
from pickit.inspector import Inspector  # noqa: E402

changes = []
inspector = Inspector(lambda k, v: changes.append((k, v)), lambda: None)
seen = set()
for item in gallery_mod.items():
    def walk(node):
        if node.get("type") not in seen:
            seen.add(node["type"])
            inspector.show_node(node, theme.default_tokens(), ["playpause"])
            assert inspector.grid.get_children(), node["type"]
        for child in node.get("children", []):
            walk(child)
    walk(item.spec["ui"])
assert not changes, "building editors must not report edits"
print(f"ok: inspector editors for {len(seen)} component types")
