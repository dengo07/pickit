"""HTML engine: a widget page in a transparent WebKit view (desktop or maker preview).

Pages are served from Pickit's own `pickit-widget://<host>/` scheme, not from file:// URLs:
the scheme serves nothing but the widget's own HTML, so widget scripts can't read local
files, and each widget is its own origin (its own localStorage). Every page gets a Content
Security Policy that lets it load fonts and libraries from a few CDNs but not send data
anywhere, and it can't navigate away or open windows.
"""

import hashlib
import itertools
import json
import re
import weakref
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("Soup", "3.0")
from gi.repository import Gdk, Gio, GLib, Soup, WebKit2  # noqa: E402

from . import theme as themes  # noqa: E402
from .bridge import BRIDGE_JS, CommandRunner  # noqa: E402

SCHEME = "pickit-widget"
# The CDNs the AI instructions allow (prompts/system.md) may serve scripts, styles and fonts.
# Nothing may send data out: no fetch/XHR/WebSocket/beacons, no remote images, forms or frames.
CDNS = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"
CSP = "; ".join([
    "default-src 'none'",
    f"script-src 'unsafe-inline' 'unsafe-eval' {CDNS}",
    f"style-src 'unsafe-inline' https://fonts.googleapis.com {CDNS}",
    f"font-src data: https://fonts.gstatic.com {CDNS}",
    "img-src data: blob:",
    "media-src data: blob:",
    "connect-src 'none'",
    "form-action 'none'",
    "frame-src 'none'",
    "worker-src 'none'",
    "base-uri 'none'",
])

_pages: dict[str, str] = {}  # host -> the HTML that pickit-widget://host/ serves
_view_numbers = itertools.count(1)
_scheme_registered = False


def _register_scheme():
    """Once per process, before the first page loads."""
    global _scheme_registered
    if _scheme_registered:
        return
    context = WebKit2.WebContext.get_default()
    context.register_uri_scheme(SCHEME, _serve)
    # "Secure", so https fonts and libraries aren't blocked as mixed content. Deliberately
    # not "local": local schemes may read file:// URLs.
    context.get_security_manager().register_uri_scheme_as_secure(SCHEME)
    _scheme_registered = True


def _serve(request):
    parts = urlsplit(request.get_uri())
    html = _pages.get(parts.hostname or "")
    if html is None or parts.path not in ("", "/"):  # the page itself and nothing else
        request.finish_error(GLib.Error.new_literal(Gio.io_error_quark(), "Not found",
                                                    Gio.IOErrorEnum.NOT_FOUND))
        return
    data = GLib.Bytes.new(html.encode())
    response = WebKit2.URISchemeResponse.new(Gio.MemoryInputStream.new_from_bytes(data), data.get_size())
    response.set_content_type("text/html; charset=utf-8")
    headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
    # A header, not a <meta>: the page can add restrictions of its own but never lift these.
    headers.append("Content-Security-Policy", CSP)
    response.set_http_headers(headers)
    request.finish_with_response(response)


def host_for(name: str) -> str:
    """A valid host name for a widget id (ids are already, unless someone renamed a folder)."""
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
        return name
    return "w-" + hashlib.sha256(name.encode()).hexdigest()[:20]


WATCHDOG_SECONDS = 30
MAX_CRASH_RELOADS = 5  # per 10 minutes, so a page that always crashes doesn't loop forever

# Desktop widgets share one WebKit web process instead of one each ("related views"),
# which is most of their memory. The trade-off: a crash or hang restarts all of them.
SHARE_WEB_PROCESS = True

# "Select part" in the maker's preview: outline elements on hover and report the clicked one.
SELECT_JS = r"""
(() => {
  if (!window.__pickitSelect) {
    const style = document.createElement("style");
    style.textContent = ".__pk-hover{outline:2px dashed rgba(240,166,74,.95)!important;outline-offset:1px}" +
                        ".__pk-sel{outline:2px solid #f0a64a!important;outline-offset:1px}";
    const strip = (el) => el.classList.remove("__pk-hover", "__pk-sel");
    const cssPath = (el) => {
      const parts = [];
      for (; el && el.nodeType === 1 && el !== document.documentElement; el = el.parentElement) {
        if (el.id) { parts.unshift("#" + el.id); break; }
        let part = el.localName;
        const cls = [...el.classList].filter((c) => !c.startsWith("__pk")).slice(0, 2);
        if (cls.length) part += "." + cls.join(".");
        const siblings = el.parentElement ? [...el.parentElement.children] : [];
        const same = siblings.filter((c) => c.localName === el.localName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(el) + 1})`;
        parts.unshift(part);
      }
      return parts.join(" > ");
    };
    let hover = null, selected = null;
    const pick = (el) => {
      if (selected) selected.classList.remove("__pk-sel");
      if (!el || el === document.documentElement) { selected = null; return; }
      strip(el);
      let html = el.outerHTML.replace(/ class=""/g, "");
      if (html.length > 1500) html = html.slice(0, 1500) + "…";
      selected = el;
      el.classList.add("__pk-sel");
      window.webkit.messageHandlers.widget.postMessage(JSON.stringify({
        type: "select", selector: cssPath(el), tag: el.localName, html,
        text: (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40)}));
    };
    const over = (e) => {
      if (hover) hover.classList.remove("__pk-hover");
      hover = e.target;
      hover.classList.add("__pk-hover");
    };
    const block = (e) => { e.preventDefault(); e.stopPropagation(); };
    const click = (e) => { block(e); pick(e.target); };
    const opts = {capture: true};
    window.__pickitSelect = {
      on() {
        document.head.appendChild(style);
        document.addEventListener("mouseover", over, opts);
        document.addEventListener("mousedown", block, opts);
        document.addEventListener("click", click, opts);
      },
      off() {
        document.removeEventListener("mouseover", over, opts);
        document.removeEventListener("mousedown", block, opts);
        document.removeEventListener("click", click, opts);
        if (hover) hover.classList.remove("__pk-hover");
        hover = null;
      },
      parent() { if (selected) pick(selected.parentElement); },
      clear() { if (selected) selected.classList.remove("__pk-sel"); selected = null; },
    };
  }
  return window.__pickitSelect;
})()"""
_shared_views: "weakref.WeakSet[WidgetView]" = weakref.WeakSet()


class WidgetView(WebKit2.WebView):
    """A WebView with the `window.widget` bridge. Commands run only if `run_commands`."""

    def __init__(self, developer_extras=False, background: str | None = None, shared=False):
        _register_scheme()
        manager = WebKit2.UserContentManager()
        manager.add_script(WebKit2.UserScript(
            BRIDGE_JS, WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, None, None))
        manager.register_script_message_handler("widget")
        manager.connect("script-message-received::widget", self._on_message)
        self._manager = manager
        self.theme = themes.default_tokens()
        self._apply_theme_css()
        kwargs = {"user_content_manager": manager}
        anchor = next(iter(_shared_views), None) if shared and SHARE_WEB_PROCESS else None
        if anchor is not None:
            kwargs["related_view"] = anchor  # same web process as the other widgets
        super().__init__(**kwargs)
        if shared:
            _shared_views.add(self)

        settings = self.get_settings()
        settings.set_enable_developer_extras(developer_extras)
        color = Gdk.RGBA(0, 0, 0, 0)
        if background:
            color.parse(background)
        self.set_background_color(color)
        self.connect("load-changed", self._on_load_changed)
        self.connect("web-process-terminated", self._on_web_process_terminated)
        self.connect("decide-policy", self._on_decide_policy)

        # Previews get a host of their own; desktop widgets use their id, so they keep their
        # localStorage across restarts.
        self._host = f"view-{next(_view_numbers)}"
        self._loads = 0
        self.runner: CommandRunner | None = None
        self._commands: dict = {}
        self._run_commands = False
        self._last_load: tuple | None = None
        self._loaded = False
        self._ping_pending = False
        self._watchdog = 0
        self._crashes: list[float] = []
        self.on_drag = None  # callable(button) set by the hosting window
        self._on_select = None  # "Select part" callback in the maker preview

    def load_widget(self, html: str, commands: dict, run_commands: bool, host: str | None = None):
        """`host` is the page's origin: the widget id on the desktop, or this view's own."""
        self._stop_runner()
        self._last_load = (html, commands, run_commands, host)
        self._commands = commands or {}
        self._run_commands = run_commands and bool(self._commands)
        self._loaded = self._ping_pending = False
        if host:
            _pages.pop(self._host, None)
            self._host = host_for(host)
        _pages[self._host] = html
        self._loads += 1  # a new URL each time, so WebKit never shows a cached page
        self.load_uri(f"{SCHEME}://{self._host}/?load={self._loads}")

    def reload_widget(self):
        if self._last_load:
            self.load_widget(*self._last_load)

    def refresh(self, max_interval: float | None = None):
        """Fetch fresh data now, e.g. after resume or when the power supply changes."""
        if self.runner:
            self.runner.refresh(max_interval)

    def set_theme(self, tokens: dict):
        """Restyle: the CSS variables change live, and `pickit-theme` fires for scripts."""
        if tokens == self.theme:
            return
        self.theme = tokens
        self._apply_theme_css()
        if self._loaded:
            self._send_theme()

    def _apply_theme_css(self):
        # A user style sheet applies before the page's own CSS runs, so no flash of defaults.
        self._manager.remove_all_style_sheets()
        self._manager.add_style_sheet(WebKit2.UserStyleSheet(
            themes.css_variables(self.theme), WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserStyleLevel.USER, None, None))

    def _send_theme(self):
        self._js(f"window.widget && window.widget._theme({json.dumps(self.theme)})")

    def _on_load_changed(self, _view, event):
        if event != WebKit2.LoadEvent.FINISHED:
            return
        self._loaded = True
        self._send_theme()
        if self._on_select:
            self._js(f"{SELECT_JS}.on()")
        if self._run_commands:
            self._stop_runner()
            self.runner = CommandRunner(self._commands, self._deliver)
            self.runner.start()

    def _on_decide_policy(self, _view, decision, kind):
        """The page may reload itself (or follow #links), but never leave: no navigating
        elsewhere, no new windows, no downloads. CSP alone doesn't cover those."""
        types = WebKit2.PolicyDecisionType
        if kind == types.NAVIGATION_ACTION:
            parts = urlsplit(decision.get_navigation_action().get_request().get_uri())
            if parts.scheme == SCHEME and parts.hostname == self._host:
                return False
            decision.ignore()
            return True
        if kind == types.NEW_WINDOW_ACTION or (kind == types.RESPONSE and not decision.is_mime_type_supported()):
            decision.ignore()
            return True
        return False

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

    # --- selecting parts (maker preview) ---------------------------------------------------
    def set_select_mode(self, on_select):
        """on_select(info) gets {selector, tag, html, text} for the clicked element; None turns
        select mode off."""
        self._on_select = on_select
        if self._loaded:
            self._js(f"{SELECT_JS}.{'on' if on_select else 'off'}()")

    def select_parent(self):
        self._js(f"{SELECT_JS}.parent()")

    def select(self, _info=None):
        """Only clearing is needed from outside: the page marks what the user clicked."""
        if _info is None and self._loaded:
            self._js(f"{SELECT_JS}.clear()")

    def _js(self, code: str):
        self.evaluate_javascript(code, -1, None, None, None, None, None)

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
        elif msg.get("type") == "select" and self._on_select:  # only while the maker asked for it
            self._on_select({k: str(msg.get(k, ""))[:2000] for k in ("selector", "tag", "html", "text")})

    def _stop_runner(self):
        if self.runner:
            self.runner.stop()
            self.runner = None

    def shutdown(self):
        self._stop_runner()
        _pages.pop(self._host, None)
        if self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = 0
