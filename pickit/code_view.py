"""A small code editor: monospace, JSON/HTML highlighting, undo/redo, two-space tabs.

(Gtk.TextView has no undo or highlighting, and GtkSourceView isn't in every runtime we ship on.)
"""

import re

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

# Mid-tone colors that read on both light and dark themes.
COLORS = {"key": "#5b9bd5", "string": "#5fa35a", "number": "#d19a50", "literal": "#d0706b",
          "tag": "#5b9bd5", "attr": "#d19a50", "comment": "#8a8f98"}
RULES = {
    "json": [("key", re.compile(r'"(?:[^"\\\n]|\\.)*"(?=\s*:)')),
             ("string", re.compile(r'"(?:[^"\\\n]|\\.)*"')),
             ("number", re.compile(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")),
             ("literal", re.compile(r"\b(?:true|false|null)\b"))],
    "html": [("comment", re.compile(r"<!--.*?-->", re.DOTALL)),
             ("string", re.compile(r'(?<==)\s*(?:"[^"]*"|\'[^\']*\')')),
             ("attr", re.compile(r"(?<=\s)[A-Za-z_:][-\w:.]*(?==)")),
             ("tag", re.compile(r"</?[A-Za-z][\w-]*|/?>"))],
}
MAX_HIGHLIGHT = 200_000  # characters; beyond this, plain text keeps typing fast
UNDO_DEPTH = 200


class CodeView(Gtk.TextView):
    def __init__(self, language: str = "json"):
        super().__init__(monospace=True, wrap_mode=Gtk.WrapMode.NONE, left_margin=10, right_margin=10,
                         top_margin=8, bottom_margin=8, accepts_tab=True)
        self.get_style_context().add_class("cmd")  # the explicit monospace font list
        self.language = language
        self.on_changed = None  # called when the user edits the text
        buf = self.get_buffer()
        for name, color in COLORS.items():
            buf.create_tag(name, foreground=color)
        focus = buf.create_tag("focus")
        rgba = Gdk.RGBA()
        rgba.parse("rgba(240,166,74,0.28)")
        focus.props.background_rgba = rgba
        self._loading = False
        self._pending = 0
        self._undo: list[tuple[str, int]] = []
        self._redo: list[tuple[str, int]] = []
        buf.connect("changed", self._on_changed)
        self.connect("key-press-event", self._on_key)

    # --- content ---------------------------------------------------------------------------
    def set_code(self, text: str, language: str | None = None):
        self.language = language or self.language
        # Pretty-printed JSON reads best unwrapped; HTML often has very long lines.
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if self.language == "html" else Gtk.WrapMode.NONE)
        self._loading = True
        self.get_buffer().set_text(text)
        self._loading = False
        self._undo, self._redo = [(text, 0)], []
        self.get_buffer().place_cursor(self.get_buffer().get_start_iter())
        self._highlight()

    def get_code(self) -> str:
        buf = self.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def show_span(self, start: int, end: int):
        """Select and scroll to characters start..end, and tint them until the next edit."""
        buf = self.get_buffer()
        a, b = buf.get_iter_at_offset(start), buf.get_iter_at_offset(end)
        buf.remove_tag_by_name("focus", buf.get_start_iter(), buf.get_end_iter())
        buf.apply_tag_by_name("focus", a, b)
        buf.select_range(a, a)
        self.scroll_to_iter(a, 0.05, True, 0.0, 0.2)
        self.grab_focus()

    # --- editing ---------------------------------------------------------------------------
    def _on_changed(self, buf):
        if self._loading:
            return
        buf.remove_tag_by_name("focus", buf.get_start_iter(), buf.get_end_iter())
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(350, self._settle)
        if self.on_changed:
            self.on_changed()

    def _settle(self):
        self._pending = 0
        self._highlight()
        self._snapshot()
        return False

    def _snapshot(self):
        text = self.get_code()
        if not self._undo or self._undo[-1][0] != text:
            cursor = self.get_buffer().get_iter_at_mark(self.get_buffer().get_insert()).get_offset()
            self._undo = (self._undo + [(text, cursor)])[-UNDO_DEPTH:]
            self._redo = []

    def _restore(self, text, cursor):
        buf = self.get_buffer()
        self._loading = True
        buf.set_text(text)
        self._loading = False
        buf.place_cursor(buf.get_iter_at_offset(min(cursor, len(text))))
        self._highlight()
        if self.on_changed:
            self.on_changed()

    def undo(self):
        if self._pending:  # take the edit in progress first
            GLib.source_remove(self._pending)
            self._pending = 0
            self._snapshot()
        if len(self._undo) > 1:
            self._redo.append(self._undo.pop())
            self._restore(*self._undo[-1])

    def redo(self):
        if self._redo:
            self._undo.append(self._redo.pop())
            self._restore(*self._undo[-1])

    def _on_key(self, _w, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        if ctrl and key == Gdk.KEY_z:
            self.redo() if shift else self.undo()
            return True
        if ctrl and key == Gdk.KEY_y:
            self.redo()
            return True
        if event.keyval == Gdk.KEY_Tab and not ctrl:
            self.get_buffer().insert_at_cursor("  ")
            return True
        return False

    # --- highlighting ------------------------------------------------------------------------
    def _highlight(self):
        buf = self.get_buffer()
        start, end = buf.get_start_iter(), buf.get_end_iter()
        for name in COLORS:
            buf.remove_tag_by_name(name, start, end)
        text = self.get_code()
        if len(text) > MAX_HIGHLIGHT:
            return
        taken = bytearray(len(text))  # earlier rules win (a JSON key isn't also a string)
        for name, pattern in RULES.get(self.language, []):
            for m in pattern.finditer(text):
                a, b = m.span()
                if a == b or taken.find(1, a, b) != -1:
                    continue
                taken[a:b] = b"\x01" * (b - a)
                buf.apply_tag_by_name(name, buf.get_iter_at_offset(a), buf.get_iter_at_offset(b))
