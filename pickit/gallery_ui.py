"""The gallery window: browse ready-made widgets, add them or open them in the editor."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import gallery  # noqa: E402
from .dialogs import PREVIEW_BG, label  # noqa: E402
from .widget_window import engine_of, make_view  # noqa: E402

CARD_WIDTH = 296
PREVIEW_MAX = (CARD_WIDTH - 24, 190)  # previews larger than this are drawn scaled down


class ScaledPreview(Gtk.DrawingArea):
    """Draws a live widget view scaled down, so every gallery card can have the same width.
    The view itself lives in an offscreen window; its redraws (clock ticks) are mirrored here."""

    def __init__(self, view: Gtk.Widget, width: int, height: int):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.view, self.scale = view, min(1.0, PREVIEW_MAX[0] / width, PREVIEW_MAX[1] / height)
        self.set_size_request(round(width * self.scale), round(height * self.scale))
        self.offscreen = Gtk.OffscreenWindow()
        view.set_size_request(width, height)
        self.offscreen.add(view)
        self.offscreen.show_all()
        self.offscreen.connect("damage-event", lambda *_: self.queue_draw() or False)
        self.connect("draw", self._draw)
        self.connect("destroy", lambda _w: self.offscreen.destroy())

    def _draw(self, _w, cr):
        cr.scale(self.scale, self.scale)
        self.view.draw(cr)
        return False


class GalleryWindow(Gtk.Window):
    def __init__(self, maker):
        super().__init__(title="Gallery", transient_for=maker, destroy_with_parent=True)
        self.maker = maker
        self.set_default_size(1120, 780)
        header = Gtk.HeaderBar(show_close_button=True, title="Gallery",
                               subtitle="Ready-made widgets. No AI needed.")
        self.set_titlebar(header)
        import_btn = Gtk.Button(label="Import file…", tooltip_text="Open a widget someone shared (.pickit)")
        import_btn.connect("clicked", lambda _b: self.maker.choose_import())
        header.pack_end(import_btn)

        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, valign=Gtk.Align.START,
                           column_spacing=18, row_spacing=18, min_children_per_line=3, max_children_per_line=5,
                           border_width=20)
        self.views = []
        for item in gallery.items():
            child = Gtk.FlowBoxChild(can_focus=False)
            child.add(self._card(item))
            flow.add(child)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(flow)
        self.add(scroller)
        self.connect("destroy", self._on_destroy)
        self.show_all()
        self.set_focus(None)  # no focus ring on the first card's button

    def _card(self, item: gallery.Item) -> Gtk.Widget:
        spec = item.spec
        width = CARD_WIDTH
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.START)
        card.get_style_context().add_class("gallery-card")

        stage = Gtk.EventBox(name="preview-bg")
        stage.get_style_context().add_class("gallery-stage")
        stage.set_size_request(width, PREVIEW_MAX[1] + 24)
        engine = engine_of(spec)
        view = make_view(engine, {}, desktop=False, background=PREVIEW_BG)
        # Never runs the commands: the preview shows the item's sample output instead.
        view.load_widget(spec["ui"] if engine == "native" else spec["html"], spec["commands"], False)
        if engine == "native":
            view.show_sample(item.sample)
            stage.add(ScaledPreview(view, spec["width"], spec["height"]))
        else:  # WebKit can't be mirrored this way; show it at full size
            view.set_size_request(spec["width"], spec["height"])
            view.set_halign(Gtk.Align.CENTER)
            view.set_valign(Gtk.Align.CENTER)
            stage.add(view)
        self.views.append(view)
        card.pack_start(stage, False, False, 0)

        title = label(f"<b>{GLib.markup_escape_text(spec['name'])}</b>")
        title.set_use_markup(True)
        card.pack_start(title, False, False, 0)
        desc = label(item.description, max_width_chars=1)  # wrap to the card's width
        desc.set_size_request(width, -1)
        desc.get_style_context().add_class("dim")
        card.pack_start(desc, False, False, 0)
        n = len(spec["commands"])
        meta = label(f"{item.category} · " + (f"{n} command{'s' if n != 1 else ''}" if n else "no commands"))
        meta.set_tooltip_text("Commands run only after you approve them." if n else "Nothing to approve.")
        meta.set_ellipsize(Pango.EllipsizeMode.END)
        meta.set_line_wrap(False)
        meta.get_style_context().add_class("dim")
        card.pack_start(meta, False, False, 0)

        buttons = Gtk.Box(spacing=8, margin_top=4)
        customize = Gtk.Button(label="Customize", tooltip_text="Open it in the editor to change it first")
        customize.connect("clicked", lambda _b: self.maker.open_spec(
            dict(item.spec), f"Gallery: {spec['name']}", origin="the gallery"))
        add = Gtk.Button(label="Add to desktop")
        add.get_style_context().add_class("suggested-action")
        add.connect("clicked", self._on_add, item)
        buttons.pack_end(add, False, False, 0)
        buttons.pack_end(customize, False, False, 0)
        card.pack_start(buttons, False, False, 0)
        return card

    def _on_add(self, button, item):
        if not self.maker.add_from_gallery(item, parent=self):
            return
        button.set_label("Added ✓")
        button.set_sensitive(False)

        def restore():
            button.set_label("Add another")
            button.set_sensitive(True)
            return False
        GLib.timeout_add(2500, restore)

    def _on_destroy(self, _w):
        for view in self.views:
            view.shutdown()
        self.views = []
