"""A desktop widget window: borderless, transparent, in the desktop layer.

The content is drawn by one of two engines: native GTK (`native.render.NativeView`) or
HTML in WebKit (`html_view.WidgetView`). WebKit is only imported for HTML widgets, so a
desktop with only native widgets never loads it.

The window itself is either a Wayland layer-shell surface or an X11 window with dock hints;
see session.py for which one and why.
"""

import os

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402
except (ImportError, ValueError):  # not installed: X11 windows only
    GtkLayerShell = None

from . import bridge, placement, store  # noqa: E402

MARGIN = placement.MARGIN
_layer_shell: bool | None = None


def layer_shell() -> bool:
    """True if widgets are layer-shell surfaces on this display (Wayland), False for X11."""
    global _layer_shell
    if _layer_shell is None:
        display = Gdk.Display.get_default()
        _layer_shell = bool(GtkLayerShell and display and "Wayland" in type(display).__name__
                            and hasattr(GtkLayerShell, "is_supported") and GtkLayerShell.is_supported())
    return _layer_shell


def layer_namespace(env=os.environ) -> str:
    """The layer-shell namespace for widget surfaces. KWin (KDE Plasma) turns it into a window
    type, and Show Desktop (Meta+D) hides every unknown one like a normal window. "dock" keeps
    widgets on the desktop, like Plasma's panels. Only from Plasma 6: KWin 5 also stacks dock
    layer surfaces above every window, whatever their layer. Elsewhere the namespace is just a
    name that users can match in compositor rules (Hyprland's layerrule, for example)."""
    plasma = "KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    version = env.get("KDE_SESSION_VERSION", "")
    return "dock" if plasma and version.isdigit() and int(version) >= 6 else "pickit-widget"


def dialog_parent(window):
    """A widget window as a dialog's parent: layer surfaces can't parent normal windows."""
    return None if window is None or getattr(window, "layer", False) else window


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


def monitors() -> list:
    display = Gdk.Display.get_default()
    return [display.get_monitor(i) for i in range(display.get_n_monitors())]


def monitor_label(index: int, monitor) -> str:
    g = monitor.get_geometry()
    name = monitor.get_model() or monitor.get_manufacturer() or ""
    return f"Monitor {index + 1}" + (f": {name}" if name else "") + f" ({g.width}×{g.height})"


def chosen_monitor(manifest: dict):
    """The monitor a widget asked for, or None (the primary one) if unset or unplugged."""
    index, found = manifest.get("monitor"), monitors()
    return found[index] if isinstance(index, int) and 0 <= index < len(found) else None


def _anchor_position(position: str, width: int, height: int, monitor=None):
    display = Gdk.Display.get_default()
    monitor = monitor or display.get_primary_monitor() or display.get_monitor(0)
    area = monitor.get_workarea()
    return placement.anchor_xy(position, (area.x, area.y, area.width, area.height), width, height)


def _on_some_monitor(x: int, y: int, width: int, height: int) -> bool:
    """Whether the middle of a widget at (x, y) is on a connected monitor (X11)."""
    cx, cy = x + width // 2, y + height // 2
    for m in monitors():
        g = m.get_geometry()
        if g.x <= cx < g.x + g.width and g.y <= cy < g.y + g.height:
            return True
    return False


def _layer_edges():
    return {"top": GtkLayerShell.Edge.TOP, "bottom": GtkLayerShell.Edge.BOTTOM,
            "left": GtkLayerShell.Edge.LEFT, "right": GtkLayerShell.Edge.RIGHT}


class WidgetWindow(Gtk.Window):
    """A borderless desktop widget. `callbacks` provides edit/delete/approve/close actions."""

    def __init__(self, manifest: dict, cfg: dict, callbacks: dict, theme: dict | None = None):
        super().__init__(title=f"Widget: {manifest['name']}")
        self.theme = theme
        self.manifest = manifest
        self.callbacks = callbacks
        self._save_timer = 0
        self._drag = None  # (pointer_x, pointer_y, window_x, window_y) while dragging
        self.signature = store.signature(manifest)
        self.layer = layer_shell()
        self._anchors: dict[str, int] = {}
        self.lock_all = cfg.get("lock_widgets", False)
        self.expanded = False
        self._expand_timer = 0  # pending shrink after a collapse animation
        self._expand_save_timer = 0
        self._expand_limiter = bridge.ExpandLimiter()
        self._drag_moved = False  # did the last press-drag move the widget (so it wasn't a click)?

        _transparent_window(self)
        self.set_decorated(False)
        self.set_resizable(False)
        if self.layer:
            # A layer-shell surface in the "bottom" layer: above the wallpaper, below every
            # window, on every workspace, and never in a taskbar, dock or Alt+Tab.
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, layer_namespace())
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        else:
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            # DOCK + keep-below puts the window in the WM's "bottom" layer: always above the
            # desktop background/icons, always below every normal window, not hidden by
            # Show Desktop, and never raised when clicked. (A DESKTOP-type window would get
            # buried under Nemo's desktop window as soon as the desktop is clicked.)
            # Its WM_CLASS is the daemon's program name, "pickit-widget" (see __main__.py).
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
        if self.theme:
            self.view.set_theme(self.theme)
        self.view.enable_watchdog()
        self.view.on_drag = self._begin_drag
        if engine == "html":
            self.view.on_expand = self.request_expand  # the page can only ask
        else:
            self.view.on_expand_request = self.request_expand
            self.view.dragged = lambda: self._drag_moved
        self._tell_view_expanded()
        self.view.connect("button-press-event", self._on_button_press)
        if engine == "html":
            self.view.connect("context-menu", lambda *a: True)  # we show our own menu
        self.add(self.view)
        self.view.show_all()

    def apply_manifest(self, manifest: dict, reposition: bool = False):
        self.manifest = manifest
        self.signature = store.signature(manifest)
        self._cancel_expand_timers()
        self.expanded = store.is_expanded(manifest)  # restored without animation
        w, h = self._target_size(manifest, self.expanded)
        self.set_size_request(w, h)
        self.resize(w, h)
        self._tell_view_expanded()
        moved = "x" in manifest and not reposition
        monitor = chosen_monitor(manifest)
        if self.layer:
            if monitor is not None:
                GtkLayerShell.set_monitor(self, monitor)
            elif GtkLayerShell.get_monitor(self) is not None:  # its monitor was unplugged
                GtkLayerShell.set_monitor(self, Gdk.Display.get_default().get_monitor(0))
            # (Unset, the compositor picks the output. Older gtk-layer-shell can't be given None.)
            self._set_anchors(placement.layer_moved(manifest["x"], manifest["y"]) if moved
                              else placement.layer_anchors(manifest.get("position", "top-right")))
        else:
            if moved and not _on_some_monitor(manifest["x"], manifest["y"], w, h):
                moved = False  # it was on a monitor that's gone: back to its corner
            x, y = ((manifest["x"], manifest["y"]) if moved
                    else _anchor_position(manifest.get("position", "top-right"), w, h, monitor))
            self.move(x, y)
        self.update_flags(manifest)
        self.reload()

    def set_theme(self, tokens: dict):
        self.theme = tokens
        self.view.set_theme(tokens)

    def update_flags(self, manifest: dict):
        """Apply the switches that don't need a reload (store.LIVE_FIELDS)."""
        for key in ("locked", "click_through"):
            self.manifest[key] = manifest.get(key, False)
        # An empty input region lets every click through to whatever is underneath.
        self.input_shape_combine_region(cairo.Region() if self.manifest["click_through"] else None)

    def locked(self) -> bool:
        return bool(self.manifest.get("locked") or self.lock_all)

    def _set_anchors(self, anchors: dict[str, int]):
        self._anchors = dict(anchors)
        for name, edge in _layer_edges().items():
            GtkLayerShell.set_anchor(self, edge, name in anchors)
            GtkLayerShell.set_margin(self, edge, anchors.get(name, 0))

    def reload(self):
        wid = self.manifest["id"]
        if engine_of(self.manifest) != self.engine:
            self._set_view(engine_of(self.manifest))
        commands, approved = self.manifest.get("commands", {}), store.is_approved(self.manifest)
        if self.engine == "native":
            self.view.load_widget(store.load_ui(wid), commands, approved)
        else:
            self.view.load_widget(store.load_html(wid), commands, approved, host=wid)

    def _reassert_layer(self, *_):
        self.set_keep_below(True)
        self.stick()
        return False

    # --- expanding ----------------------------------------------------------
    # The one code path that changes the window size. The size comes from the manifest's
    # validated `expandable` block, never from a page or a message.
    def can_expand(self) -> bool:
        return isinstance(self.manifest.get("expandable"), dict)  # a hand-edited file can hold anything

    def _work_area(self) -> tuple[int, int]:
        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        monitor = (display.get_monitor_at_window(gdk_window) if gdk_window else None) \
            or chosen_monitor(self.manifest) or display.get_primary_monitor() or display.get_monitor(0)
        area = monitor.get_workarea()
        return area.width, area.height

    def _target_size(self, manifest: dict, expanded: bool) -> tuple[int, int]:
        # A hand-edited widget.json can hold anything: every size is clamped, and a bad one
        # falls back to the collapsed (or the default) size.
        collapsed = placement.safe_size(manifest.get("width"), manifest.get("height"), None, (320, 200))
        size = manifest.get("expandable")
        if expanded and isinstance(size, dict):
            return placement.safe_size(size.get("width"), size.get("height"), self._work_area(), collapsed)
        return collapsed

    def _cancel_expand_timers(self):
        if self._expand_timer:
            GLib.source_remove(self._expand_timer)
            self._expand_timer = 0

    def _tell_view_expanded(self, animate: bool = False):
        if self.engine == "html":
            self.view.set_expanded_state(self.expanded)
        else:
            self.view.set_expanded(self.expanded, animate)

    def request_expand(self, action: str):
        """A request from content ("expand", "collapse" or "toggle"). Rate limited."""
        if action not in bridge.EXPAND_ACTIONS or not self.can_expand():
            return
        if not self._expand_limiter.allow(GLib.get_monotonic_time() / 1000):
            return
        self.set_expanded(bridge.expand_target(action, self.expanded))

    def set_expanded(self, on: bool, animate: bool = True):
        if not self.can_expand() or bool(on) == self.expanded:
            return
        self.expanded = bool(on)
        self._cancel_expand_timers()
        if self.expanded:
            self._apply_size()  # grow first, then let the content reveal
            self._tell_view_expanded(animate)
        else:
            self._tell_view_expanded(animate)  # hide first, then shrink once it has finished
            animations = Gtk.Settings.get_default().get_property("gtk-enable-animations")
            if animate and animations:
                self._expand_timer = GLib.timeout_add(bridge.EXPAND_MS, self._finish_collapse)
            else:
                self._apply_size()
        self._schedule_expanded_save()

    def _finish_collapse(self):
        self._expand_timer = 0
        self._apply_size()
        return False

    def _apply_size(self):
        w, h = self._target_size(self.manifest, self.expanded)
        self.set_size_request(w, h)
        self.resize(w, h)
        screen = self._screen_size()
        # Pushed back on screen to fit the expanded size, it returns to where it was on collapse.
        before = getattr(self, "_pre_expand", None) if not self.expanded else None
        self._pre_expand = None
        if self.layer:
            # Anchored to an edge it grows away from it. A dragged widget is pinned by its
            # top-left corner, so keep the new size on screen.
            if "top" in self._anchors and "left" in self._anchors:
                x, y = before or (self._anchors["left"], self._anchors["top"])
                nx, ny = placement.clamp(x, y, screen, (w, h))
                if self.expanded and (nx, ny) != (x, y):
                    self._pre_expand = (x, y)
                self._set_anchors(placement.layer_moved(nx, ny))
        else:
            x, y = before or self.get_position()
            nx, ny = placement.clamp(x, y, screen, (w, h))
            if self.expanded and (nx, ny) != (x, y):
                self._pre_expand = (x, y)
            if (nx, ny) != self.get_position():
                self.move(nx, ny)

    def _schedule_expanded_save(self):
        if self._expand_save_timer:
            GLib.source_remove(self._expand_save_timer)
        self._expand_save_timer = GLib.timeout_add(600, self._save_expanded)

    def _save_expanded(self):
        self._expand_save_timer = 0
        try:
            manifest = store.load(self.manifest["id"])
        except (OSError, ValueError):  # gone, or half-written by someone else
            return False
        if store.is_expanded(manifest) != self.expanded and isinstance(manifest.get("expandable"), dict):
            if self.expanded:
                manifest["expanded"] = True
            else:
                manifest.pop("expanded", None)  # a widget that is collapsed carries no field
            store.save_manifest(manifest, notify=False)
            self.manifest["expanded"] = self.expanded
        return False

    # --- moving -----------------------------------------------------------
    # Dock windows can't be moved by the WM, so dragging is done by hand: poll the
    # pointer while the button is held and move the window along with it.
    def _begin_drag(self, _button=1):
        self._drag_moved = False
        if self._drag or self.locked():
            return
        if self.layer:
            self._begin_layer_drag()
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
        if abs(px - sx) > 4 or abs(py - sy) > 4:
            self._drag_moved = True
        self.move(wx + px - sx, wy + py - sy)
        if mask & Gdk.ModifierType.BUTTON1_MASK:
            return True
        self._drag = None
        self._save_position()
        return False

    # Wayland has no global pointer position; it's only known relative to our own surface,
    # which moves along with the drag. So each step moves the widget by how far the pointer
    # has slipped from the point where it grabbed the widget.
    def _screen_size(self):
        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        monitor = display.get_monitor_at_window(gdk_window) if gdk_window else None
        monitor = monitor or display.get_monitor(0)
        geometry = monitor.get_geometry()
        return geometry.width, geometry.height

    def _size(self):
        return self.get_allocated_width(), self.get_allocated_height()

    def _pointer(self):
        """(x, y, modifier mask) of the pointer, relative to this surface."""
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        _, px, py, mask = self.get_window().get_device_position(pointer)
        return px, py, mask

    def _begin_layer_drag(self):
        px, py, _ = self._pointer()
        x, y = placement.layer_top_left(self._anchors, self._screen_size(), self._size())
        self._set_anchors(placement.layer_moved(x, y))
        self._drag = [px, py, x, y, False]
        GLib.timeout_add(16, self._layer_drag_step)

    def _layer_drag_step(self):
        px, py, mask = self._pointer()
        sx, sy, x, y, just_moved = self._drag
        if not just_moved:  # skip one step after a move, so the compositor has applied it
            nx, ny = placement.clamp(x + px - sx, y + py - sy, self._screen_size(), self._size())
            if abs(px - sx) > 4 or abs(py - sy) > 4:
                self._drag_moved = True
            if (nx, ny) != (x, y):
                self._set_anchors(placement.layer_moved(nx, ny))
                self._drag[2:] = [nx, ny, True]
        else:
            self._drag[4] = False
        if mask & Gdk.ModifierType.BUTTON1_MASK:
            return True
        self._drag = None
        self._save_layer_position()
        return False

    def _save_layer_position(self):
        x, y = placement.layer_top_left(self._anchors, self._screen_size(), self._size())
        try:
            manifest = store.load(self.manifest["id"])
        except FileNotFoundError:
            return
        if (manifest.get("x"), manifest.get("y")) != (x, y):
            manifest["x"], manifest["y"] = x, y
            store.save_manifest(manifest, notify=False)
            self.manifest = manifest

    def _on_button_press(self, _view, event):
        if event.button == 1 and event.state & Gdk.ModifierType.MOD1_MASK:
            self._begin_drag()
            return True
        if event.button == 3:
            self._menu().popup_at_pointer(event)
            return True
        return False

    def _on_configure(self, _win, _event):
        if self._drag or self.layer:  # a layer surface's position is only changed by our drags
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
        # Remember the monitor it was dragged to, so "Reset position" keeps it there.
        display = Gdk.Display.get_default()
        w, h = self._size()
        found = display.get_monitor_at_point(x + w // 2, y + h // 2)
        index = next((i for i, m in enumerate(monitors()) if m == found), None)
        changed = (manifest.get("x"), manifest.get("y")) != (x, y)
        if index is not None and len(monitors()) > 1 and manifest.get("monitor") != index:
            manifest["monitor"], changed = index, True
        if changed:
            manifest["x"], manifest["y"] = x, y
            store.save_manifest(manifest, notify=False)
            self.manifest = manifest
        return False

    # --- context menu -----------------------------------------------------
    def _menu(self):
        menu = Gtk.Menu()
        items = [("Edit…", "edit"), ("Reload", "reload")]
        if self.can_expand():
            items.insert(0, ("Collapse" if self.expanded else "Expand", "expand"))
        if self.manifest.get("commands"):
            items.append(("Review commands…", "approve"))
        items += [None, ("Lock position", "lock"), ("Click-through", "click_through"),
                  ("Reset position", "reset")]
        if len(monitors()) > 1:
            items.append(("Move to monitor", "monitor"))
        items += [None, ("Export…", "export"), ("Hide", "hide"), ("Delete", "delete")]
        for item in items:
            if item is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            label, action = item
            if action in ("lock", "click_through"):
                mi = Gtk.CheckMenuItem(label=label, active=self.locked() if action == "lock"
                                       else bool(self.manifest.get("click_through")))
                if action == "lock" and self.lock_all:
                    mi.set_sensitive(False)
                    mi.set_tooltip_text("All widgets are locked in Pickit's settings")
                if action == "click_through":
                    mi.set_tooltip_text("Clicks go to the desktop underneath. Turn it off in Pickit's "
                                        "sidebar (⋮ next to the widget).")
            elif action == "monitor":
                mi = Gtk.MenuItem(label=label)
                sub = Gtk.Menu()
                current = chosen_monitor(self.manifest)
                for i, m in enumerate(monitors()):
                    choice = Gtk.CheckMenuItem(label=monitor_label(i, m), active=m == current)
                    choice.set_draw_as_radio(True)
                    choice.connect("activate", lambda _mi, i=i: self._move_to_monitor(i))
                    sub.append(choice)
                mi.set_submenu(sub)
                menu.append(mi)
                continue
            else:
                mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _mi, a=action: self._menu_action(a))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self)
        return menu

    def _move_to_monitor(self, index: int):
        manifest = store.load(self.manifest["id"])
        manifest["monitor"] = index
        manifest.pop("x", None)
        manifest.pop("y", None)
        store.save_manifest(manifest, notify=False)
        self.apply_manifest(manifest, reposition=True)

    def _menu_action(self, action):
        wid = self.manifest["id"]
        if action == "expand":
            self.set_expanded(not self.expanded)
        elif action == "reload":
            self.apply_manifest(store.load(wid))
        elif action in ("lock", "click_through"):
            manifest = store.load(wid)
            key = "locked" if action == "lock" else "click_through"
            manifest[key] = not manifest.get(key, False)
            store.save_manifest(manifest)  # the Pickit window's sidebar follows
            self.update_flags(manifest)
        elif action == "reset":
            manifest = store.load(wid)
            manifest.pop("x", None)
            manifest.pop("y", None)
            store.save_manifest(manifest, notify=False)
            self.apply_manifest(manifest, reposition=True)
        else:
            self.callbacks[action](wid)
