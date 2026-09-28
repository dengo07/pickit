"""Wayland smoke test: run inside a compositor with layer-shell, for example headless sway:

    WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 sway -c tests/sway-headless.conf &
    WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland python3 tests/wayland_smoke.py

Checks that widgets become layer-shell surfaces in the bottom layer at the right anchors, that
dragging moves them (simulating a compositor that applies each move one step late), and that
menus pop up from them.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PICKIT_DATA_HOME"] = tempfile.mkdtemp()
os.environ["PICKIT_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("GDK_BACKEND", "wayland")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

from pickit import placement, store  # noqa: E402
from pickit.widget_window import WidgetWindow, dialog_parent, layer_shell  # noqa: E402

assert layer_shell(), "this compositor should offer layer-shell"
loop = GLib.MainLoop()


def settle(ms=300):
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def spec(position):
    return {"name": position, "engine": "native", "width": 160, "height": 60, "position": position,
            "commands": {}, "ui": {"type": "card", "children": [{"type": "label", "text": position}]}}


Edge = GtkLayerShell.Edge
windows = {}
for position in ("top-left", "top-right", "bottom-center", "center-left", "center"):
    w = WidgetWindow(store.save_spec(spec(position)), {}, {})
    w.show_all()
    windows[position] = w
settle()
for position, w in windows.items():
    assert GtkLayerShell.is_layer_window(w)
    assert GtkLayerShell.get_layer(w) == GtkLayerShell.Layer.BOTTOM
    anchored = {name for name, edge in (("top", Edge.TOP), ("bottom", Edge.BOTTOM), ("left", Edge.LEFT),
                                        ("right", Edge.RIGHT)) if GtkLayerShell.get_anchor(w, edge)}
    assert anchored == set(placement.layer_anchors(position)), (position, anchored)
    assert dialog_parent(w) is None
print(f"ok: {len(windows)} widgets are bottom-layer layer-shell surfaces at their anchors")

# A widget the user moved is pinned by its top-left corner.
moved = store.save_spec(spec("top-right"))
moved.update(x=300, y=200)
store.save_manifest(moved)
mw = WidgetWindow(moved, {}, {})
mw.show_all()
settle()
assert GtkLayerShell.get_anchor(mw, Edge.TOP) and GtkLayerShell.get_anchor(mw, Edge.LEFT)
assert not GtkLayerShell.get_anchor(mw, Edge.RIGHT)
assert (GtkLayerShell.get_margin(mw, Edge.LEFT), GtkLayerShell.get_margin(mw, Edge.TOP)) == (300, 200)
print("ok: moved widgets keep their position")

# Drag the top-right widget by (-400, +250). The fake compositor applies each move one step
# late, as a real one may: the pointer position is relative to where the surface really is.
w = windows["top-right"]
screen, size = w._screen_size(), w._size()
real = list(placement.layer_top_left(w._anchors, screen, size))
grab = (40, 20)
pointer = [real[0] + grab[0], real[1] + grab[1]]
state = {"held": True, "pending": None}


def fake_pointer():
    if state["pending"] is not None:      # the compositor catches up with the last move
        real[:] = state["pending"]
    state["pending"] = placement.layer_top_left(w._anchors, screen, size)
    mask = Gdk.ModifierType.BUTTON1_MASK if state["held"] else 0
    return pointer[0] - real[0], pointer[1] - real[1], mask


w._pointer = fake_pointer
start = tuple(real)
w._begin_drag()
for _ in range(25):
    pointer[0] -= 16
    pointer[1] += 10
    settle(20)
state["held"] = False
settle(120)
end = placement.layer_top_left(w._anchors, screen, size)
assert w._drag is None, "the drag should end when the button is released"
assert abs(end[0] - (start[0] - 400)) <= 2 and abs(end[1] - (start[1] + 250)) <= 2, (start, end)
saved = store.load(w.manifest["id"])
assert (saved["x"], saved["y"]) == end, "the new position should be saved"
print(f"ok: dragging moved the widget from {start} to {end} and saved it")

# The right-click menu pops up from a layer surface.
menu = w._menu()
menu.popup_at_widget(w.view, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
settle()
assert menu.get_visible() and menu.get_toplevel().get_mapped(), "the widget menu should appear"
menu.popdown()
print("ok: the widget menu pops up from a layer surface")

# With two outputs, a widget can be moved to the second one (CI creates it with swaymsg).
from pickit.widget_window import monitors  # noqa: E402

if len(monitors()) > 1:
    on_second = store.save_spec(spec("top-right"))
    sw = WidgetWindow(on_second, {}, {})
    sw.show_all()
    settle()
    assert GtkLayerShell.get_monitor(sw) is None       # by default the compositor picks
    sw._move_to_monitor(1)
    settle()
    assert GtkLayerShell.get_monitor(sw) == monitors()[1]
    assert store.load(on_second["id"])["monitor"] == 1
    labels = [i.get_label() for i in sw._menu().get_children() if isinstance(i, Gtk.MenuItem)]
    assert "Move to monitor" in labels
    windows["second"] = sw
    print("ok: widgets can move to another monitor")
else:
    print("skipped: only one monitor (create a second with `swaymsg create_output`)")

for win in (*windows.values(), mw):
    win.destroy()
Gtk.main_iteration_do(False)
