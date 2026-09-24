"""A desktop widget window: borderless, transparent, in the desktop layer.

The content is drawn by one of two engines: native GTK (`native.render.NativeView`) or
HTML in WebKit (`html_view.WidgetView`). WebKit is only imported for HTML widgets, so a
desktop with only native widgets never loads it.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import store  # noqa: E402

MARGIN = 24


def engine_of(manifest: dict) -> str:
    return "native" if manifest.get("engine") == "native" else "html"


def make_view(engine: str, cfg: dict, desktop: bool = True, background: str | None = None):
    """Create the view for an engine. Imports are lazy on purpose (see module docstring)."""
    if engine == "native":
        from .native.render import NativeView
        return NativeView(background=background)
    from .html_view import WidgetView
    return WidgetView(cfg.get("developer_extras", False), background=background, shared=desktop)
def _transparent_window(win: Gtk.Window):
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual and screen.is_composited():
        win.set_visual(visual)
    win.set_app_paintable(True)

    def draw(_w, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(1)  # cairo.OPERATOR_SOURCE
        cr.paint()
        cr.set_operator(2)  # cairo.OPERATOR_OVER
        return False

    win.connect("draw", draw)


def _anchor_position(position: str, width: int, height: int):
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    area = monitor.get_workarea()
    vert, _, horiz = position.partition("-")
    if position == "center":
        vert, horiz = "center", "center"
    x = {"left": area.x + MARGIN,
         "center": area.x + (area.width - width) // 2,
         "right": area.x + area.width - width - MARGIN}.get(horiz, area.x + area.width - width - MARGIN)
    y = {"top": area.y + MARGIN,
         "center": area.y + (area.height - height) // 2,
         "bottom": area.y + area.height - height - MARGIN}.get(vert, area.y + MARGIN)
    return x, y


class WidgetWindow(Gtk.Window):
    """A borderless desktop widget. `callbacks` provides edit/delete/approve/close actions."""

    def __init__(self, manifest: dict, cfg: dict, callbacks: dict):
        super().__init__(title=f"Widget: {manifest['name']}")
        self.manifest = manifest
        self.callbacks = callbacks
        self._save_timer = 0
        self._drag = None  # (pointer_x, pointer_y, window_x, window_y) while dragging
        self.signature = store.signature(manifest)

        _transparent_window(self)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # Not "pickit": that class belongs to the Pickit launcher (StartupWMClass), and docks
        # such as Plank would show widgets as a running Pickit app.
        self.set_wmclass("pickit-widget", "PickitWidget")
        # DOCK + keep-below puts the window in the WM's "bottom" layer: always above the
        # desktop background/icons, always below every normal window, not hidden by
        # Show Desktop, and never raised when clicked. (A DESKTOP-type window would get
        # buried under Nemo's desktop window as soon as the desktop is clicked.)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_below(True)
        self.stick()
        self.connect("map-event", self._reassert_layer)

        self.cfg = cfg
        self.view = None
        self._set_view(engine_of(manifest))

        self.apply_manifest(manifest)
        self.connect("configure-event", self._on_configure)
        self.connect("destroy", lambda *_: self.view.shutdown())

    def _set_view(self, engine: str):
        """(Re)create the content view, e.g. when a refine switched the widget's engine."""
        if self.view is not None:
            self.view.shutdown()
            self.remove(self.view)
            self.view.destroy()
        self.engine = engine
        self.view = make_view(engine, self.cfg)
        self.view.enable_watchdog()
        self.view.on_drag = self._begin_drag
        self.view.connect("button-press-event", self._on_button_press)
        if engine == "html":
            self.view.connect("context-menu", lambda *a: True)  # we show our own menu
        self.add(self.view)
        self.view.show_all()

    def apply_manifest(self, manifest: dict, reposition: bool = False):
        self.manifest = manifest
        self.signature = store.signature(manifest)
        w, h = manifest["width"], manifest["height"]
        self.set_size_request(w, h)
        self.resize(w, h)
        if reposition or "x" not in manifest:
            x, y = _anchor_position(manifest.get("position", "top-right"), w, h)
        else:
            x, y = manifest["x"], manifest["y"]
        self.move(x, y)
        self.reload()

    def reload(self):
        wid = self.manifest["id"]
        if engine_of(self.manifest) != self.engine:
            self._set_view(engine_of(self.manifest))
        commands, approved = self.manifest.get("commands", {}), store.is_approved(self.manifest)
        if self.engine == "native":
            self.view.load_widget(store.load_ui(wid), commands, approved)
        else:
            self.view.load_widget(store.load_html(wid), commands, approved, store.html_path(wid).as_uri())

    def _reassert_layer(self, *_):
        self.set_keep_below(True)
        self.stick()
        return False

    # --- moving -----------------------------------------------------------
    # Dock windows can't be moved by the WM, so dragging is done by hand: poll the
    # pointer while the button is held and move the window along with it.
    def _begin_drag(self, _button=1):
        if self._drag:
            return
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        _, px, py = pointer.get_position()
        wx, wy = self.get_position()
        self._drag = (px, py, wx, wy)
        GLib.timeout_add(12, self._drag_step, pointer)

    def _drag_step(self, pointer):
        _, px, py = pointer.get_position()
        _, _, _, mask = Gdk.get_default_root_window().get_device_position(pointer)
        sx, sy, wx, wy = self._drag
        self.move(wx + px - sx, wy + py - sy)
        if mask & Gdk.ModifierType.BUTTON1_MASK:
            return True
        self._drag = None
        self._save_position()
        return False

    def _on_button_press(self, _view, event):
        if event.button == 1 and event.state & Gdk.ModifierType.MOD1_MASK:
            self._begin_drag()
            return True
        if event.button == 3:
            self._menu().popup_at_pointer(event)
            return True
        return False

    def _on_configure(self, _win, _event):
        if self._drag:
            return False
        if self._save_timer:
            GLib.source_remove(self._save_timer)
        self._save_timer = GLib.timeout_add(600, self._save_position)
        return False

    def _save_position(self):
        self._save_timer = 0
        x, y = self.get_position()
        try:
            manifest = store.load(self.manifest["id"])
        except FileNotFoundError:
            return False
        if (manifest.get("x"), manifest.get("y")) != (x, y):
            manifest["x"], manifest["y"] = x, y
            store.save_manifest(manifest, notify=False)
            self.manifest = manifest
        return False

    # --- context menu -----------------------------------------------------
    def _menu(self):
        menu = Gtk.Menu()
        items = [("Edit with AI…", "edit"), ("Reload", "reload")]
        if self.manifest.get("commands"):
            items.append(("Review commands…", "approve"))
        items += [("Reset position", "reset"), None, ("Hide", "hide"), ("Delete", "delete")]
        for item in items:
            if item is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            label, action = item
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _mi, a=action: self._menu_action(a))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self)
        return menu

    def _menu_action(self, action):
        wid = self.manifest["id"]
        if action == "reload":
            self.apply_manifest(store.load(wid))
        elif action == "reset":
            manifest = store.load(wid)
            manifest.pop("x", None)
            manifest.pop("y", None)
            store.save_manifest(manifest, notify=False)
            self.apply_manifest(manifest, reposition=True)
        else:
            self.callbacks[action](wid)
