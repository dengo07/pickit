"""Native engine: renders a component tree with GTK3 widgets and Cairo — no WebKit.

The tree is built once. Each property that depends on data becomes a *binding* that
re-evaluates only when one of the data sources it reads changes, and only touches GTK
when its value actually changed, so an idle widget does no work at all.
"""

import base64
import collections
import datetime
import itertools
import threading
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from ..bridge import CommandRunner  # noqa: E402
from . import data as D  # noqa: E402
from . import draw  # noqa: E402
from .spec import SAFE_CSS  # noqa: E402

SHADOW_CSS = {"soft": "0 4px 14px rgba(0,0,0,0.35)", "medium": "0 6px 20px rgba(0,0,0,0.45)",
              "strong": "0 10px 30px rgba(0,0,0,0.6)"}
SHADOW_ROOM = {"soft": 12, "medium": 16, "strong": 24}  # margin so the shadow isn't clipped
WEIGHT_CSS = {"light": 300, "normal": 400, "medium": 500, "semibold": 600, "bold": 700, "heavy": 800}
CARD_DEFAULTS = {"background": "rgba(18,18,24,0.78)", "radius": 16, "padding": 12, "shadow": "soft",
                 "spacing": 6, "border": "rgba(255,255,255,0.08)", "border_width": 1}
ALIGN = {"start": Gtk.Align.START, "center": Gtk.Align.CENTER, "end": Gtk.Align.END, "fill": Gtk.Align.FILL}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ids = itertools.count(1)
_image_cache: "collections.OrderedDict[str, GdkPixbuf.Pixbuf]" = collections.OrderedDict()


def _px(value) -> str:
    if isinstance(value, list):
        sides = (value * 4)[:4] if len(value) == 1 else (value + value)[:4] if len(value) == 2 else \
            [value[0], value[1], value[2], value[1]] if len(value) == 3 else value
        return " ".join(f"{int(v)}px" for v in sides)
    return f"{int(value)}px"


def _sides(value):
    """margin/padding → (top, right, bottom, left)."""
    if isinstance(value, list):
        v = value
        return {1: (v[0],) * 4, 2: (v[0], v[1], v[0], v[1]), 3: (v[0], v[1], v[2], v[1])}.get(len(v), tuple(v[:4]))
    return (value,) * 4


def _safe(value):
    return value if isinstance(value, str) and SAFE_CSS.match(value) else None


def _set_icon(image: Gtk.Image, name: str, size: int):
    """Show a theme icon only if the theme has it. A made-up name would make GTK fall back to
    its "missing image" icon, and a failing image loader turns that into a fatal error."""
    if name and Gtk.IconTheme.get_default().has_icon(name):
        image.set_from_icon_name(name, Gtk.IconSize.BUTTON)
        image.set_pixel_size(size)
    else:
        image.clear()


class _Binding:
    __slots__ = ("deps", "apply", "last")

    def __init__(self, deps, apply):
        self.deps, self.apply, self.last = deps, apply, object()


class NativeView(Gtk.EventBox):
    """Same interface as the HTML engine's WidgetView (load_widget, refresh, …)."""

    def __init__(self, background: str | None = None):
        super().__init__()
        self.set_visible_window(False)
        self.connect("button-press-event", self._on_press)
        self.on_drag = None
        self.runner: CommandRunner | None = None
        self.data: dict = {}
        self._bindings: list[_Binding] = []
        self._styles: dict[str, dict] = {}
        self._css = Gtk.CssProvider()
        self._css_screen = False
        self._clock = 0
        self._last_load: tuple | None = None
        self._commands: dict = {}

    # --- lifecycle ------------------------------------------------------------------
    def load_widget(self, ui: dict, commands: dict, run_commands: bool, base_uri: str | None = None):
        self.shutdown()
        self._last_load = (ui, commands, run_commands, base_uri)
        self._commands = commands or {}
        for child in self.get_children():
            self.remove(child)
            child.destroy()
        self.data = {"now": datetime.datetime.now()}
        self._bindings, self._styles = [], {}
        self.add(self._build(ui))
        self._flush_css()
        self._update(None)
        self.show_all()
        if any("now" in b.deps for b in self._bindings):
            self._schedule_tick()
        if run_commands and self._commands:
            self.runner = CommandRunner(self._commands, self._deliver)
            self.runner.start()

    def reload_widget(self):
        if self._last_load:
            self.load_widget(*self._last_load)

    def refresh(self, max_interval: float | None = None):
        if self.runner:
            self.runner.refresh(max_interval)

    def enable_watchdog(self):
        """Nothing to watch: there is no separate page process that could hang or crash."""

    def shutdown(self):
        if self.runner:
            self.runner.stop()
            self.runner = None
        if self._clock:
            GLib.source_remove(self._clock)
            self._clock = 0

    # --- data -----------------------------------------------------------------------
    def _deliver(self, key, result):
        # Keep the last good value if a command fails, so a hiccup doesn't blank the widget.
        if result.get("code", 0) == 0 or key not in self.data:
            self.data[key] = D.parse_output(result.get("out", ""))
            self._update({key})

    def _schedule_tick(self):
        now = datetime.datetime.now()
        delay = 1000 - now.microsecond // 1000 + 5  # land just after the next full second
        self._clock = GLib.timeout_add(delay, self._tick)

    def _tick(self):
        self.data["now"] = datetime.datetime.now()
        self._update({"now"})
        self._schedule_tick()
        return False

    def _update(self, changed: set | None):
        styles_before = repr(self._styles)
        for b in self._bindings:
            if changed is None or b.deps & changed:
                b.apply(self.data)
        if repr(self._styles) != styles_before:
            self._flush_css()

    def _bind(self, props: dict, keys, apply):
        """Call `apply(values)` now and whenever a data source used by `props[keys]` changes."""
        keys = [k for k in keys if k in props]
        if not keys:
            return
        deps = set().union(*(D.refs(props[k]) for k in keys))

        def run(data, b=None):
            values = {k: D.resolve(props[k], data) for k in keys}
            if binding.last != values:
                binding.last = values
                apply(values)

        binding = _Binding(deps, run)
        self._bindings.append(binding)

    # --- styling ----------------------------------------------------------------------
    def _style(self, widget, **decls):
        name = widget.get_name()
        if not name.startswith("pk"):
            name = f"pk{next(_ids)}"
            widget.set_name(name)
        rule = self._styles.setdefault(name, {})
        for prop, value in decls.items():
            if value is None:
                rule.pop(prop, None)
            else:
                rule[prop] = value

    def _flush_css(self):
        css = "".join(f"#{name} {{{''.join(f'{p}:{v};' for p, v in rule.items())}}}\n"
                      for name, rule in self._styles.items() if rule)
        self._css.load_from_data(css.encode())
        if not self._css_screen:
            from gi.repository import Gdk
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self._css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self._css_screen = True

    # --- building -----------------------------------------------------------------------
    def _build(self, node: dict) -> Gtk.Widget:
        kind = node["type"]
        props = dict(CARD_DEFAULTS, **node) if kind == "card" else node
        widget = getattr(self, f"_make_{kind}")(props)
        self._common(widget, props)
        return widget

    def _common(self, w, p):
        margin = p.get("margin")
        if margin is None and p["type"] == "card" and p.get("shadow", "none") != "none":
            margin = SHADOW_ROOM.get(p["shadow"], 0)
        if margin is not None:
            top, right, bottom, left = _sides(margin)
            w.set_margin_top(top)
            w.set_margin_end(right)
            w.set_margin_bottom(bottom)
            w.set_margin_start(left)
        if "width" in p or "height" in p:
            w.set_size_request(p.get("width", -1), p.get("height", -1))
        for key, setter in (("halign", w.set_halign), ("valign", w.set_valign)):
            if key in p:
                setter(ALIGN[p[key]])
        if "hexpand" in p:
            w.set_hexpand(p["hexpand"])
        if "vexpand" in p:
            w.set_vexpand(p["vexpand"])
        if "visible" in p:
            # show_all() skips no-show-all widgets and their children, so show them now and
            # let the binding decide the widget's own visibility from here on.
            w.show_all()
            w.set_no_show_all(True)
            self._bind(p, ["visible"], lambda v: w.set_visible(D.condition(p["visible"], self.data)))
        if "tooltip" in p:
            self._bind(p, ["tooltip"], lambda v: w.set_tooltip_text(D.to_text(v["tooltip"]) or None))
        if "opacity" in p:
            self._bind(p, ["opacity"], lambda v: w.set_opacity(
                max(0.0, min(1.0, D.to_number(v["opacity"]) or 1.0))))

    def _box(self, p, orientation):
        box = Gtk.Box(orientation=orientation, spacing=p.get("spacing", 0))
        horizontal = orientation == Gtk.Orientation.HORIZONTAL
        for child in p.get("children", []):
            widget = self._build(child)
            if child.get("type") == "spacer" and "size" not in child:
                # A flexible spacer grows along its box only, never across it.
                widget.set_hexpand(horizontal)
                widget.set_vexpand(not horizontal)
            # fill=True: expanding children really get the space; halign/valign still apply.
            box.pack_start(widget, False, True, 0)
        static = {}
        if "padding" in p:
            static["padding"] = _px(p["padding"])
        if "radius" in p:
            static["border-radius"] = f"{int(p['radius'])}px"
        if p.get("shadow", "none") != "none":
            static["box-shadow"] = SHADOW_CSS[p["shadow"]]
        if static:
            self._style(box, **static)

        def colors(v):
            bg, border = _safe(v.get("background")), _safe(v.get("border"))
            self._style(box, background=bg, **{
                "border": f"{int(p.get('border_width', 1))}px solid {border}" if border else None})
        self._bind(p, ["background", "border"], colors)
        return box

    def _make_column(self, p):
        return self._box(p, Gtk.Orientation.VERTICAL)

    def _make_card(self, p):
        return self._box(p, Gtk.Orientation.VERTICAL)

    def _make_row(self, p):
        return self._box(p, Gtk.Orientation.HORIZONTAL)

    def _make_overlay(self, p):
        overlay = Gtk.Overlay()
        children = p.get("children", [])
        if children:
            overlay.add(self._build(children[0]))
            for child in children[1:]:
                overlay.add_overlay(self._build(child))
        return overlay

    def _make_spacer(self, p):
        box = Gtk.Box()
        if "size" in p:
            box.set_size_request(p["size"], p["size"])
        else:
            box.set_hexpand(True)
            box.set_vexpand(True)
        return box

    def _make_label(self, p):
        label = Gtk.Label()
        label.set_xalign({"start": 0.0, "center": 0.5, "end": 1.0}[p.get("align", "start")])
        label.set_justify({"start": Gtk.Justification.LEFT, "center": Gtk.Justification.CENTER,
                           "end": Gtk.Justification.RIGHT}[p.get("align", "start")])
        if p.get("ellipsize"):
            label.set_ellipsize(Pango.EllipsizeMode.END)
        if p.get("wrap"):
            label.set_line_wrap(True)
        static = {}
        if "weight" in p:
            static["font-weight"] = str(WEIGHT_CSS[p["weight"]])
        if "font" in p and _safe(str(p["font"])):
            static["font-family"] = str(p["font"])
        if "letter_spacing" in p and isinstance(p["letter_spacing"], (int, float)):
            static["letter-spacing"] = f"{p['letter_spacing']}px"
        if p.get("text_shadow"):
            static["text-shadow"] = "0 1px 3px rgba(0,0,0,0.6)"
        self._style(label, **static)
        self._bind(p, ["text"], lambda v: label.set_text(D.to_text(v["text"])))

        def look(v):
            size = D.to_number(v.get("size"))
            self._style(label, color=_safe(v.get("color")), **{"font-size": f"{size:g}px" if size else None})
        self._bind(p, ["color", "size"], look)
        return label

    def _make_icon(self, p):
        if "name" in p:
            image = Gtk.Image()
            size = int(D.to_number(p.get("size")) or 24)

            self._bind(p, ["name"], lambda v: _set_icon(image, D.to_text(v["name"]), size))
            self._bind(p, ["color"], lambda v: self._style(image, color=_safe(v["color"])))
            return image
        return self._make_label({"type": "label", "text": p.get("text", ""), "size": p.get("size", 24),
                                 **({"color": p["color"]} if "color" in p else {})})

    def _area(self, width, height, draw_fn, hexpand=False):
        area = Gtk.DrawingArea()
        area.set_size_request(width, height)
        area.set_hexpand(hexpand)
        area.connect("draw", lambda a, cr: draw_fn(cr, a.get_allocated_width(), a.get_allocated_height()))
        return area

    def _make_progress(self, p):
        state = {}
        thickness = int(D.to_number(p.get("thickness")) or 6)
        area = self._area(-1, thickness, lambda cr, w, h: draw.bar(
            cr, w, h, draw.fraction(state.get("value"), state.get("max", 100)),
            draw.rgba(state.get("color"), (1, 1, 1, 0.9)), draw.rgba(state.get("track"), (1, 1, 1, 0.15)),
            D.to_number(p.get("radius")) if "radius" in p else thickness / 2), hexpand=True)

        def upd(v):
            state.update(value=D.to_number(v.get("value")), max=D.to_number(v.get("max")) or 100,
                         color=v.get("color"), track=v.get("track"))
            area.queue_draw()
        self._bind(p, ["value", "max", "color", "track"], upd)
        return area

    def _make_ring(self, p):
        state = {}
        size = p.get("size", 120)
        area = self._area(size, size, lambda cr, w, h: draw.ring(
            cr, w, h, draw.fraction(state.get("value"), state.get("max", 100)),
            D.to_number(p.get("thickness")) or max(4, size / 12),
            draw.rgba(state.get("color"), (0.29, 0.87, 0.5, 1)),
            draw.rgba(state.get("track"), (1, 1, 1, 0.12)), D.to_number(p.get("start")) or -90.0))

        def upd(v):
            state.update(value=D.to_number(v.get("value")), max=D.to_number(v.get("max")) or 100,
                         color=v.get("color"), track=v.get("track"))
            area.queue_draw()
        self._bind(p, ["value", "max", "color", "track"], upd)
        children = p.get("children", [])
        if not children:
            return area
        overlay = Gtk.Overlay()
        overlay.add(area)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        for child in children:
            center.pack_start(self._build(child), False, True, 0)
        overlay.add_overlay(center)
        return overlay

    def _make_sparkline(self, p):
        points = collections.deque(maxlen=p.get("points", 30))
        state = {}
        area = self._area(-1, 40, lambda cr, w, h: draw.sparkline(
            cr, w, h, list(points), D.to_number(p.get("min")) if "min" in p else None,
            D.to_number(p.get("max")) if "max" in p else None, draw.rgba(state.get("color"), (1, 1, 1, 0.9)),
            draw.rgba(state["fill"], None) if state.get("fill") else None,
            D.to_number(p.get("line_width")) or 2), hexpand=True)

        def upd(v):
            state.update(color=v.get("color"), fill=v.get("fill"))
            value = D.to_number(v.get("value"))
            if value is not None:
                points.append(value)
            area.queue_draw()
        # Record every delivery, even if the value repeats, so the line keeps moving in time.
        deps = D.refs(p["value"]) | D.refs(p.get("color")) | D.refs(p.get("fill"))
        self._bindings.append(_Binding(deps, lambda data: upd(
            {k: D.resolve(p[k], data) for k in ("value", "color", "fill") if k in p})))
        return area

    def _make_image(self, p):
        state = {"pixbuf": None, "src": None}
        size = int(D.to_number(p.get("size")) or 64)
        def paint(cr, w, h):
            if state["pixbuf"] is not None:
                draw.pixbuf(cr, w, h, state["pixbuf"], D.to_number(p.get("radius")) or 0, p.get("fit", "cover"))
            return False
        area = self._area(size, size, paint)

        def show(pb):
            state["pixbuf"] = pb
            area.queue_draw()
            return False

        def upd(v):
            src = D.to_text(v["src"]).strip()
            if src == state["src"]:
                return
            state["src"] = src
            _load_image(src, show)
        self._bind(p, ["src"], upd)
        return area

    def _make_button(self, p):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        size = D.to_number(p.get("size")) or 16
        inner = Gtk.Box(spacing=6)
        inner.set_halign(Gtk.Align.CENTER)
        if "icon" in p:
            image = Gtk.Image()
            self._bind(p, ["icon"], lambda v: _set_icon(image, D.to_text(v["icon"]), int(size)))
            inner.pack_start(image, False, False, 0)
        if "text" in p:
            label = Gtk.Label()
            self._bind(p, ["text"], lambda v: label.set_text(D.to_text(v["text"])))
            self._style(label, **{"font-size": f"{size:g}px"})
            inner.pack_start(label, False, False, 0)
        button.add(inner)
        self._style(button, **{"border-radius": f"{int(p.get('radius', 999))}px", "padding": "4px",
                               "min-width": "0", "min-height": "0", "border": "none", "box-shadow": "none"})

        def look(v):
            self._style(button, color=_safe(v.get("color")),
                        **{"background-color": _safe(v.get("background")) or "transparent",
                           "background-image": "none"})
        look({k: p.get(k) for k in ("color", "background")})
        self._bind(p, ["color", "background"], look)
        button.connect("clicked", lambda _b: self._action(p["action"]))
        return button

    def _action(self, key):
        if not self.runner:
            return
        self.runner.run(key)
        # The action probably changed something (e.g. play/pause): fetch fresh data soon.
        for delay in (350, 1200):
            GLib.timeout_add(delay, lambda: (self.runner and self.runner.refresh()) and False)

    # --- input ------------------------------------------------------------------------
    def _on_press(self, _box, event):
        if event.button == 1 and self.on_drag:
            self.on_drag(1)  # plain left-drag anywhere (except buttons) moves the widget
            return True
        return False


def _load_image(src: str, done):
    """Load an image from a data: URL, a local path/file:// URL or http(s), then call done(pixbuf)."""
    if not src:
        done(None)
        return
    if src in _image_cache:
        _image_cache.move_to_end(src)
        done(_image_cache[src])
        return

    def finish(pb):
        if pb is not None:
            _image_cache[src] = pb
            while len(_image_cache) > 12:
                _image_cache.popitem(last=False)
        GLib.idle_add(done, pb)

    def from_bytes(raw):
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.write(raw)
            loader.close()
            return loader.get_pixbuf()
        except GLib.Error:
            return None

    if src.startswith("data:"):
        try:
            raw = base64.b64decode(src.split(",", 1)[1])
        except (IndexError, ValueError):
            raw = b""
        finish(from_bytes(raw[:MAX_IMAGE_BYTES]) if raw else None)
    elif src.startswith(("http://", "https://")):
        def fetch():
            try:
                with urllib.request.urlopen(src, timeout=10) as r:
                    finish(from_bytes(r.read(MAX_IMAGE_BYTES)))
            except (OSError, ValueError):
                finish(None)
        threading.Thread(target=fetch, daemon=True).start()
    else:
        path = src[7:] if src.startswith("file://") else src
        try:
            with open(path, "rb") as f:
                finish(from_bytes(f.read(MAX_IMAGE_BYTES)))
        except OSError:
            finish(None)
