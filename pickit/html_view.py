"""HTML engine: a widget page in a transparent WebKit view (desktop or maker preview)."""

import json
import weakref

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, WebKit2  # noqa: E402

from .bridge import BRIDGE_JS, CommandRunner  # noqa: E402

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
