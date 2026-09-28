"""The theme editor: presets, colors, corner radius, font and light/dark mode, with a live preview."""

import copy

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import gallery  # noqa: E402
from . import theme as themes  # noqa: E402
from .dialogs import PREVIEW_BG, label  # noqa: E402
from .inspector import _css_color, _rgba  # noqa: E402
from .native.render import NativeView  # noqa: E402

PREVIEW_ITEMS = ("system-rings", "world-clock")


class ThemeDialog(Gtk.Dialog):
    def __init__(self, parent, cfg_theme: dict | None):
        super().__init__(title="Widget theme", transient_for=parent, modal=True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        self.settings = copy.deepcopy(themes.settings(cfg_theme))
        self.system_dark, self.system_accent = themes.system_appearance()
        self._loading = True

        outer = Gtk.Box(spacing=18, border_width=16)
        self.get_content_area().add(outer)
        form = Gtk.Grid(column_spacing=12, row_spacing=10)
        outer.pack_start(form, False, False, 0)

        self.preset = Gtk.ComboBoxText()
        for pid, preset in themes.PRESETS.items():
            self.preset.append(pid, preset["name"])
        self.preset.connect("changed", self._on_preset)
        self.mode = Gtk.ComboBoxText()
        for mid, text in (("dark", "Dark"), ("light", "Light"), ("system", "Follow the desktop")):
            self.mode.append(mid, text)
        self.mode.connect("changed", self._on_mode)
        rows = [("Preset", self.preset), ("Mode", self.mode)]

        self.colors = {}
        for token in themes.TOKENS:
            button = Gtk.ColorButton(use_alpha=True, halign=Gtk.Align.START)
            button.connect("color-set", self._on_color, token)
            self.colors[token] = button
            rows.append((themes.LABELS[token], button))

        self.radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 40, 1)
        self.radius.set_size_request(180, -1)
        self.radius.connect("value-changed", self._on_radius)
        rows.append(("Corner radius", self.radius))
        font_row = Gtk.Box(spacing=6)
        self.font = Gtk.FontButton(use_font=True)
        self.font.set_level(Gtk.FontChooserLevel.FAMILY)
        self.font.connect("font-set", self._on_font)
        reset_font = Gtk.Button(label="Default")
        reset_font.connect("clicked", self._on_font_default)
        font_row.pack_start(self.font, True, True, 0)
        font_row.pack_start(reset_font, False, False, 0)
        rows.append(("Font", font_row))
        self.accent_from_system = Gtk.CheckButton(label="Use the desktop's accent color")
        self.accent_from_system.set_sensitive(self.system_accent is not None)
        if self.system_accent is None:
            self.accent_from_system.set_tooltip_text("Your desktop doesn't share an accent color")
        self.accent_from_system.connect("toggled", self._on_system_accent)
        rows.append(("", self.accent_from_system))
        reset = Gtk.Button(label="Reset colors to the preset", halign=Gtk.Align.START)
        reset.connect("clicked", self._on_reset)
        rows.append(("", reset))
        for i, (text, widget) in enumerate(rows):
            form.attach(label(text), 0, i, 1, 1)
            form.attach(widget, 1, i, 1, 1)

        # Live preview: two gallery widgets with their sample data.
        stage = Gtk.EventBox(name="preview-bg")
        stage.get_style_context().add_class("gallery-stage")
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, border_width=20,
                         valign=Gtk.Align.CENTER)
        stage.add(column)
        items = {i.id: i for i in gallery.items()}
        self.previews = []
        for item_id in PREVIEW_ITEMS:
            item = items[item_id]
            view = NativeView(background=PREVIEW_BG)
            view.set_size_request(item.spec["width"], item.spec["height"])
            view.set_halign(Gtk.Align.CENTER)
            view.load_widget(item.spec["ui"], item.spec["commands"], False)
            self.previews.append((view, item))
            column.pack_start(view, False, False, 0)
        outer.pack_start(stage, True, True, 0)

        self._sync_controls()
        self._loading = False
        self._refresh_preview()
        self.show_all()

    # --- state ------------------------------------------------------------------------------
    def tokens(self) -> dict:
        return themes.tokens(self.settings, self.system_dark, self.system_accent)

    def _sync_controls(self):
        self._loading = True
        s, t = self.settings, self.tokens()
        self.preset.set_active_id(s["preset"])
        self.mode.set_active_id(s["mode"])
        for token, button in self.colors.items():
            if (c := _rgba(t[token])) is not None:
                button.set_rgba(c)
        self.radius.set_value(s["radius"])
        self.font.set_font(s["font"] or Gtk.Settings.get_default().props.gtk_font_name)
        self.accent_from_system.set_active(bool(s["system_accent"]))
        self._loading = False

    def _changed(self):
        if not self._loading:
            self._refresh_preview()

    def _refresh_preview(self):
        t = self.tokens()
        for view, item in self.previews:
            view.set_theme(t)
            view.show_sample(item.sample)

    # --- handlers ---------------------------------------------------------------------------
    def _on_preset(self, combo):
        if self._loading:
            return
        self.settings["preset"] = combo.get_active_id()
        self.settings["overrides"] = {}   # a preset brings its own colors
        self._sync_controls()
        self._changed()

    def _on_mode(self, combo):
        if not self._loading:
            self.settings["mode"] = combo.get_active_id()
            self._sync_controls()
            self._changed()

    def _on_color(self, button, token):
        self.settings["overrides"][token] = _css_color(button.get_rgba())
        if token == "accent":
            self.settings["system_accent"] = False
            self.accent_from_system.set_active(False)
        self._changed()

    def _on_radius(self, scale):
        if not self._loading:
            self.settings["radius"] = int(scale.get_value())
            self._changed()

    def _on_font(self, button):
        family = button.get_font_family()
        self.settings["font"] = family.get_name() if family else ""
        self._changed()

    def _on_font_default(self, _button):
        self.settings["font"] = ""
        self._sync_controls()
        self._changed()

    def _on_system_accent(self, check):
        if not self._loading:
            self.settings["system_accent"] = check.get_active()
            if check.get_active():
                self.settings["overrides"].pop("accent", None)
            self._sync_controls()
            self._changed()

    def _on_reset(self, _button):
        self.settings["overrides"] = {}
        self._sync_controls()
        self._changed()

