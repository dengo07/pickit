"""Hosts a widget's HTML in a transparent WebKit view, as a preview or on the desktop."""

import json
import weakref

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

from . import store  # noqa: E402
from .bridge import BRIDGE_JS, CommandRunner  # noqa: E402

MARGIN = 24
WATCHDOG_SECONDS = 30
MAX_CRASH_RELOADS = 5  # per 10 minutes, so a page that always crashes doesn't loop forever

# Desktop widgets share one WebKit web process instead of one each ("related views"),
# which is most of their memory. The trade-off: a crash or hang restarts all of them.
SHARE_WEB_PROCESS = True
_shared_views: "weakref.WeakSet[WidgetView]" = weakref.WeakSet()


class WidgetView(WebKit2.WebView):
    """A WebView with the `window.widget` bridge. Commands run only if `run_commands`."""

    def __init__(self, developer_extras=False, background: str | None = None, shared=False):
        manager = WebKit2.UserContentManager()
        manager.add_script(WebKit2.UserScript(
            BRIDGE_JS, WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, None, None))
        manager.register_script_message_handler("widget")
        manager.connect("script-message-received::widget", self._on_message)
        kwargs = {"user_content_manager": manager}
        anchor = next(iter(_shared_views), None) if shared and SHARE_WEB_PROCESS else None
        if anchor is not None:
            kwargs["related_view"] = anchor  # same web process as the other widgets
        super().__init__(**kwargs)
        if shared:
            _shared_views.add(self)

        settings = self.get_settings()
        settings.set_enable_developer_extras(developer_extras)
        settings.set_allow_file_access_from_file_urls(True)
        color = Gdk.RGBA(0, 0, 0, 0)
        if background:
            color.parse(background)
        self.set_background_color(color)
        self.connect("load-changed", self._on_load_changed)
        self.connect("web-process-terminated", self._on_web_process_terminated)

        self.runner: CommandRunner | None = None
        self._commands: dict = {}
        self._run_commands = False
        self._last_load: tuple | None = None
        self._loaded = False
        self._ping_pending = False
        self._watchdog = 0
        self._crashes: list[float] = []
        self.on_drag = None  # callable(button) set by the hosting window

    def load_widget(self, html: str, commands: dict, run_commands: bool, base_uri: str | None = None):
        self._stop_runner()
        self._last_load = (html, commands, run_commands, base_uri)
        self._commands = commands or {}
        self._run_commands = run_commands and bool(self._commands)
        self._loaded = self._ping_pending = False
        self.load_html(html, base_uri or "file:///")

    def reload_widget(self):
        if self._last_load:
            self.load_widget(*self._last_load)

    def refresh(self, max_interval: float | None = None):
        """Fetch fresh data now, e.g. after resume or when the power supply changes."""
        if self.runner:
            self.runner.refresh(max_interval)

    def _on_load_changed(self, _view, event):
        if event != WebKit2.LoadEvent.FINISHED:
            return
        self._loaded = True
        if self._run_commands:
            self._stop_runner()
            self.runner = CommandRunner(self._commands, self._deliver)
            self.runner.start()

    # --- self-healing -------------------------------------------------------
    def _on_web_process_terminated(self, _view, reason):
        """The page's WebKit process crashed or was killed: bring the widget back."""
        now = GLib.get_monotonic_time() / 1e6
        self._crashes = [t for t in self._crashes if now - t < 600] + [now]
        self._stop_runner()
        if len(self._crashes) <= MAX_CRASH_RELOADS:
            print(f"pickit: widget page terminated ({reason.value_nick}), reloading", flush=True)
            GLib.timeout_add_seconds(2, self._reload_once)
        else:
            print("pickit: widget page keeps crashing, giving up until next reload", flush=True)

    def _reload_once(self):
        self.reload_widget()
        return False  # one-shot GLib timeout

    def enable_watchdog(self):
        """Reload the page if it stops answering (hung script or stuck web process)."""
        if not self._watchdog:
            self._watchdog = GLib.timeout_add_seconds(WATCHDOG_SECONDS, self._watchdog_tick)

    def _watchdog_tick(self):
        if not self._loaded:
            return True
        if self._ping_pending:
            # A hung page can't process a reload, so kill its process; the
            # web-process-terminated handler then loads the widget again.
            print("pickit: widget page stopped responding, restarting it", flush=True)
            self._ping_pending = False
            self._loaded = False
            self.terminate_web_process()
            return True
        self._ping_pending = True

        def pong(view, result):
            try:
                view.evaluate_javascript_finish(result)
                self._ping_pending = False
            except GLib.Error:
                pass  # leave pending: the next tick reloads

        self.evaluate_javascript("1", -1, None, None, None, pong)
        return True

    def _deliver(self, key, result):
        js = f"window.widget && window.widget._deliver({json.dumps(key)}, {json.dumps(result)});"
        self.evaluate_javascript(js, -1, None, None, None, None, None)

    def _on_message(self, _manager, js_result):
        value = js_result.get_js_value() if hasattr(js_result, "get_js_value") else js_result
        try:
            msg = json.loads(value.to_string())
        except (json.JSONDecodeError, TypeError):
            return
        if msg.get("type") == "run" and self.runner:
            self.runner.run(str(msg.get("key")))
        elif msg.get("type") == "drag" and self.on_drag:
            self.on_drag(int(msg.get("button", 0)) + 1)

    def _stop_runner(self):
        if self.runner:
            self.runner.stop()
            self.runner = None

    def shutdown(self):
        self._stop_runner()
        if self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = 0


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

        self.view = WidgetView(cfg.get("developer_extras", False), shared=True)
        self.view.enable_watchdog()
        self.view.on_drag = self._begin_drag
        self.view.connect("button-press-event", self._on_button_press)
        self.view.connect("context-menu", lambda *a: True)  # we show our own menu
        self.add(self.view)

        self.apply_manifest(manifest)
        self.connect("configure-event", self._on_configure)
        self.connect("destroy", lambda *_: self.view.shutdown())

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
        self.view.load_widget(store.load_html(wid), self.manifest.get("commands", {}),
                              store.is_approved(self.manifest),
                              store.html_path(wid).as_uri())

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
