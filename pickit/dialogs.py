"""Dialogs shared by the maker window and the desktop daemon."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

PREVIEW_BG = "#3b3f45"  # a neutral mid-tone "wallpaper" that shows both light and dark widgets well
# Named explicitly: the "monospace" alias resolves to a serif font on some systems.
MONO_FONTS = "DejaVu Sans Mono,Liberation Mono,Noto Sans Mono,JetBrains Mono,monospace"

CSS = b"""
#preview-bg { background-color: %s; }
.dim { opacity: 0.7; }
.cmd { font-family: %s; }
""" % (PREVIEW_BG.encode(), ", ".join(f'"{f}"' if " " in f else f for f in MONO_FONTS.split(",")).encode())


def install_css():
    from gi.repository import Gdk
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def label(text="", **kw):
    lbl = Gtk.Label(label=text, xalign=0, **kw)
    lbl.set_line_wrap(True)
    return lbl


def approval_dialog(parent, name: str, commands: dict) -> bool:
    """Ask the user to approve a widget's shell commands. Returns True if approved."""
    dlg = Gtk.Dialog(title="Approve widget commands", transient_for=parent, modal=True)
    dlg.add_button("Don't run commands", Gtk.ResponseType.REJECT)
    ok = dlg.add_button("Approve and run", Gtk.ResponseType.ACCEPT)
    ok.get_style_context().add_class("suggested-action")
    dlg.set_default_size(620, -1)

    box = dlg.get_content_area()
    box.set_spacing(10)
    box.set_border_width(16)
    intro = label(f"<b>{GLib.markup_escape_text(name)}</b> wants to run these shell commands "
                   "as your user. Only approve commands you understand.")
    intro.set_use_markup(True)
    box.add(intro)

    grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    for row, (key, c) in enumerate(commands.items()):
        every = f"every {c['interval']:g}s" if c["interval"] > 0 else "on load / on demand"
        head = label(f"<b>{GLib.markup_escape_text(key)}</b>\n<small>{every}</small>")
        head.set_use_markup(True)
        head.set_valign(Gtk.Align.START)
        cmd = label(c["cmd"], selectable=True)
        cmd.get_style_context().add_class("cmd")
        cmd.set_hexpand(True)
        grid.attach(head, 0, row, 1, 1)
        grid.attach(cmd, 1, row, 1, 1)
    scroller = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=420)
    scroller.add(grid)
    box.add(scroller)
    dlg.show_all()
    response = dlg.run()
    dlg.destroy()
    return response == Gtk.ResponseType.ACCEPT


def confirm(parent, text: str, action: str = "Delete") -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=text)
    dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
    btn = dlg.add_button(action, Gtk.ResponseType.OK)
    btn.get_style_context().add_class("destructive-action")
    ok = dlg.run() == Gtk.ResponseType.OK
    dlg.destroy()
    return ok
