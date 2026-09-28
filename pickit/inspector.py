"""The property inspector: edit the selected native component with pickers, sliders and boxes.

It only reports edits (`on_change(key, value)`, `value` is REMOVE to unset a property); the
Pickit window applies them to the draft through codeedit.set_property, which validates them.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import codeedit  # noqa: E402
from . import theme as themes  # noqa: E402
from .dialogs import label  # noqa: E402
from .native import spec as ui_spec  # noqa: E402

REMOVE = object()
WIDTH = 280  # the panel sits next to the preview, so it stays narrow
# (lower, upper, step) for number-like properties; anything else gets a generic range.
RANGES = {"opacity": (0, 1, 0.05), "letter_spacing": (-5, 20, 0.1), "size": (4, 400, 1),
          "thickness": (1, 60, 1), "line_width": (0.5, 20, 0.5), "start": (-360, 360, 5),
          "radius": (0, 200, 1), "spacing": (0, 200, 1), "border_width": (0, 20, 1),
          "points": (2, 500, 1), "width": (0, 4000, 1), "height": (0, 4000, 1)}
DEFAULTS = {ui_spec.COLOR: "{theme.accent}", ui_spec.NUMBER: 1, ui_spec.INT: 0, ui_spec.TEXT: "",
            ui_spec.BOOL: True, ui_spec.COND: "{now} != ''", ui_spec.MARGIN: 0}
TOKEN_CHOICES = ("accent", "text", "muted", "good", "warn", "bad", "card", "border")


def _title(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _rgba(text: str) -> Gdk.RGBA | None:
    c = Gdk.RGBA()
    return c if isinstance(text, str) and c.parse(text) else None


def _css_color(c: Gdk.RGBA) -> str:
    r, g, b = (round(v * 255) for v in (c.red, c.green, c.blue))
    return f"#{r:02x}{g:02x}{b:02x}" if c.alpha >= 0.999 else f"rgba({r},{g},{b},{c.alpha:.2f})"


def _is_template(value) -> bool:
    return isinstance(value, str) and "{" in value


class Inspector(Gtk.Box):
    def __init__(self, on_change, on_show_code):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=12)
        self.set_size_request(WIDTH, -1)
        self.on_change, self.on_show_code = on_change, on_show_code
        self.node, self.theme, self.actions = None, themes.default_tokens(), []
        self._loading = False
        self.title = label()
        self.title.set_use_markup(True)
        self.pack_start(self.title, False, False, 0)
        self.error = label()
        self.error.get_style_context().add_class("warning-note")
        self.pack_start(self.error, False, False, 0)
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pack_start(self.grid, False, False, 0)
        self.add_btn = Gtk.MenuButton(label="Add property", halign=Gtk.Align.START, margin_top=4)
        self.pack_start(self.add_btn, False, False, 0)

    # --- content -----------------------------------------------------------------------
    def show_message(self, text: str):
        self.node = None
        self.title.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        self.error.set_text("")
        self._clear()
        self.add_btn.hide()

    def show_node(self, node: dict, theme: dict, actions: list[str]):
        """Build editors for a component. Call again when the set of properties changed."""
        self.node, self.theme, self.actions = node, theme, actions
        self.title.set_markup(f"<b>{GLib.markup_escape_text(codeedit.describe(node))}</b>")
        self.error.set_text("")
        self._clear()
        self._loading = True
        props = codeedit.editable_properties(node)
        shown = 0
        for prop in props:
            if not prop["set"]:
                continue
            # Name and remove button on one line, the editor under it: fits a narrow panel.
            head = Gtk.Box(spacing=4)
            name = label(_title(prop["key"]))
            name.get_style_context().add_class("dim")
            head.pack_start(name, True, True, 0)
            remove = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
            remove.set_tooltip_text(f"Remove {prop['key']} (use the default)")
            remove.get_style_context().add_class("flat")
            remove.connect("clicked", lambda _b, k=prop["key"]: self.on_change(k, REMOVE))
            head.pack_start(remove, False, False, 0)
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.pack_start(head, False, False, 0)
            row.pack_start(self._editor(prop), False, False, 0)
            self.grid.pack_start(row, False, False, 0)
            shown += 1
        if shown == 0:
            empty = label("Nothing set yet: it uses the defaults. Add a property below.", max_width_chars=30)
            empty.get_style_context().add_class("dim")
            self.grid.pack_start(empty, False, False, 0)
        menu = Gtk.Menu()
        for prop in props:
            if prop["set"]:
                continue
            item = Gtk.MenuItem(label=_title(prop["key"]))
            item.connect("activate", lambda _i, p=prop: self.on_change(p["key"], self._default(p)))
            menu.append(item)
        menu.show_all()
        self.add_btn.set_popup(menu)
        self.add_btn.show()
        self.grid.show_all()
        self._loading = False

    def update_node(self, node: dict):
        """The same component after an edit (a new dict); keeps the editors as they are."""
        self.node = node

    def set_error(self, text: str):
        self.error.set_text(text)

    def _clear(self):
        for child in self.grid.get_children():
            self.grid.remove(child)
            child.destroy()

    def _default(self, prop):
        if prop["kind"] == ui_spec.ENUM:
            return prop["choices"][0]
        if prop["kind"] == ui_spec.ACTION:
            return self.actions[0] if self.actions else ""
        return DEFAULTS.get(prop["kind"], "")

    def _emit(self, key, value):
        if not self._loading:
            self.error.set_text("")
            self.on_change(key, value)

    # --- editors ------------------------------------------------------------------------
    def _editor(self, prop) -> Gtk.Widget:
        key, kind, value = prop["key"], prop["kind"], prop["value"]
        if isinstance(value, list) and kind not in (ui_spec.MARGIN,):
            box = Gtk.Box(spacing=6)
            note = label("Changes with data", max_width_chars=16)
            note.get_style_context().add_class("dim")
            box.pack_start(note, True, True, 0)
            code = Gtk.Button(label="Edit in code")
            code.connect("clicked", lambda _b: self.on_show_code())
            box.pack_start(code, False, False, 0)
            return box
        if kind == ui_spec.COLOR:
            return self._color_editor(key, value)
        if kind in (ui_spec.NUMBER, ui_spec.INT) and not _is_template(value):
            lo, hi, step = RANGES.get(key, (-100000, 100000, 1 if kind == ui_spec.INT else 0.5))
            spin = Gtk.SpinButton.new_with_range(lo, hi, step)
            spin.set_digits(0 if kind == ui_spec.INT or step >= 1 else 2)
            spin.set_value(float(value or 0))
            spin.connect("value-changed", lambda s: self._emit(
                key, int(s.get_value()) if kind == ui_spec.INT else round(s.get_value(), 3)))
            return spin
        if kind == ui_spec.BOOL:
            switch = Gtk.Switch(active=bool(value), halign=Gtk.Align.START)
            switch.connect("notify::active", lambda s, _p: self._emit(key, s.get_active()))
            return switch
        if kind in (ui_spec.ENUM, ui_spec.ACTION):
            combo = Gtk.ComboBoxText()
            options = prop["choices"] if kind == ui_spec.ENUM else self.actions
            for option in options:
                combo.append(option, option)
            combo.set_active_id(str(value))
            combo.connect("changed", lambda c: c.get_active_id() and self._emit(key, c.get_active_id()))
            return combo
        if kind == ui_spec.MARGIN:
            text = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            return self._entry(key, text, _parse_margin, "pixels, or top right bottom left")
        # text, conditions and number templates
        parse = (lambda t: t) if kind != ui_spec.NUMBER else _parse_number
        return self._entry(key, "" if value is None else str(value), parse)

    def _entry(self, key, text, parse, placeholder=""):
        entry = Gtk.Entry(text=text, placeholder_text=placeholder)
        entry.set_width_chars(8)

        def commit(*_):
            try:
                self._emit(key, parse(entry.get_text()))
            except ValueError as e:
                self.error.set_text(str(e))
            return False
        entry.connect("activate", commit)
        entry.connect("focus-out-event", commit)
        entry.connect("changed", lambda _e: self._debounce(entry, commit))
        return entry

    def _debounce(self, widget, fn, ms=500):
        if getattr(widget, "_pending", 0):
            GLib.source_remove(widget._pending)

        def run():
            widget._pending = 0
            fn()
            return False
        widget._pending = GLib.timeout_add(ms, run)

    def _color_editor(self, key, value) -> Gtk.Widget:
        box = Gtk.Box(spacing=4)
        token = value[7:-1] if isinstance(value, str) and value.startswith("{theme.") and value.endswith("}") \
            else None
        shown = self.theme.get(token) if token else value
        button = Gtk.ColorButton(use_alpha=True)
        button.set_tooltip_text("Pick a color")
        if (c := _rgba(shown)) is not None:
            button.set_rgba(c)
        button.connect("color-set", lambda b: self._emit(key, _css_color(b.get_rgba())))
        box.pack_start(button, False, False, 0)
        # Theme colors keep the widget matching the theme when it changes.
        themed = Gtk.MenuButton(label=themes.LABELS[token] if token else "Theme",
                                tooltip_text="Use a color from the widget theme")
        menu = Gtk.Menu()
        for name in TOKEN_CHOICES:
            item = Gtk.MenuItem(label=themes.LABELS[name])
            item.connect("activate", lambda _i, n=name: self._emit(key, f"{{theme.{n}}}"))
            menu.append(item)
        menu.show_all()
        themed.set_popup(menu)
        box.pack_start(themed, False, False, 0)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        column.pack_start(box, False, False, 0)
        if _is_template(value) and not token:  # a data-driven color: show the template
            column.pack_start(self._entry(key, value, lambda t: t), False, False, 0)
        inner = themed.get_child()
        if isinstance(inner, Gtk.Label):
            inner.set_ellipsize(Pango.EllipsizeMode.END)
        return column


def _parse_margin(text: str):
    parts = text.replace(",", " ").split()
    if not 1 <= len(parts) <= 4 or not all(p.lstrip("-").isdigit() for p in parts):
        raise ValueError("Margin: one number, or 2–4 numbers (top right bottom left)")
    values = [int(p) for p in parts]
    return values[0] if len(values) == 1 else values


def _parse_number(text: str):
    text = text.strip()
    if _is_template(text):
        return text
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        raise ValueError(f"“{text}” isn't a number or a template like {{cpu}}") from None
