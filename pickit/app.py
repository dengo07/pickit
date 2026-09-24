"""The Pickit window: describe, preview, refine and place widgets.

The widgets themselves live in the separate desktop daemon (daemon.py), so
closing this window never removes them from the desktop.
"""

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from . import autostart, backends, config, generator, runtime, store  # noqa: E402
from .dialogs import (  # noqa: E402
    PREVIEW_BG,  # noqa: E402
    approval_dialog,
    confirm,  # noqa: E402
    install_css,
    label,
)
from .widget_window import WidgetView  # noqa: E402

APP_ID = runtime.APP_ID

EXAMPLES = [
    ("Minimal clock", "A big minimalist clock with the date underneath, white text with a soft shadow"),
    ("System meters", "CPU, RAM and disk usage as slim animated bars on a dark translucent card"),
    ("Weather", "Current weather for my location with a 3-day forecast"),
    ("Now playing", "Now playing from Spotify/any player with play/pause and next buttons"),
    ("Pomodoro", "A pomodoro timer with start/pause and a circular progress ring"),
    ("Battery ring", "Battery level and charging state as a ring gauge"),
]


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, cfg: dict):
        super().__init__(title="Settings", transient_for=parent, modal=True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, border_width=16)
        self.get_content_area().add(grid)

        self.backend = Gtk.ComboBoxText()
        self.backend.append("auto", "Automatic (Claude Code if installed, else API)")
        self.backend.append("claude-cli", "Claude Code CLI (uses your Claude login)")
        self.backend.append("anthropic", "Anthropic API (API key)")
        self.backend.set_active_id(cfg["backend"])
        self.cli_model = Gtk.Entry(text=cfg["cli_model"], placeholder_text="default (e.g. opus, sonnet)")
        self.api_model = Gtk.Entry(text=cfg["api_model"])
        self.api_key = Gtk.Entry(text=cfg["anthropic_api_key"], visibility=False,
                                 placeholder_text="empty = use ANTHROPIC_API_KEY")
        self.login = Gtk.CheckButton(label="Keep widgets on the desktop after reboot (start at login)",
                                     active=cfg.get("autostart", True))
        self.devtools = Gtk.CheckButton(label="Enable web inspector in widgets",
                                        active=cfg["developer_extras"])

        rows = [("AI backend", self.backend), ("CLI model", self.cli_model),
                ("API model", self.api_model), ("API key", self.api_key),
                ("", self.login), ("", self.devtools)]
        for i, (text, widget) in enumerate(rows):
            grid.attach(label(text), 0, i, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, i, 1, 1)
        self.show_all()

    def apply(self, cfg: dict):
        cfg.update({
            "backend": self.backend.get_active_id(),
            "cli_model": self.cli_model.get_text().strip(),
            "api_model": self.api_model.get_text().strip() or config.DEFAULTS["api_model"],
            "anthropic_api_key": self.api_key.get_text().strip(),
            "autostart": self.login.get_active(),
            "developer_extras": self.devtools.get_active(),
        })
        autostart.set_enabled(self.login.get_active())


class MakerWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "PickitApp"):
        super().__init__(application=app, title="Pickit")
        self.app = app
        self.set_default_size(1100, 720)
        self.draft: dict | None = None
        self.draft_approved = False
        self.editing_id: str | None = None
        self.prompts: list[str] = []
        self.busy = False
        self.auto_place = False

        # Header
        header = Gtk.HeaderBar(show_close_button=True, title="Pickit",
                               subtitle="Describe a widget, get it on your desktop")
        self.set_titlebar(header)
        settings_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self._on_settings)
        header.pack_end(settings_btn)
        self.backend_combo = Gtk.ComboBoxText()
        self.backend_combo.append("auto", "Auto")
        self.backend_combo.append("claude-cli", "Claude CLI")
        self.backend_combo.append("anthropic", "Anthropic API")
        self.backend_combo.set_active_id(app.cfg["backend"])
        self.backend_combo.connect("changed", self._on_backend_changed)
        header.pack_end(self.backend_combo)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=280)
        self.add(paned)

        # Sidebar: widget list
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=12)
        title = label("<b>Your widgets</b>")
        title.set_use_markup(True)
        side.pack_start(title, False, False, 0)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        list_scroll.add(self.listbox)
        side.pack_start(list_scroll, True, True, 0)
        new_btn = Gtk.Button(label="New widget")
        new_btn.connect("clicked", lambda *_: self.reset_editor())
        side.pack_start(new_btn, False, False, 0)
        paned.pack1(side, False, False)

        # Main editor
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=14)
        paned.pack2(main, True, False)
        self.mode_label = label()
        self.mode_label.set_use_markup(True)
        main.pack_start(self.mode_label, False, False, 0)

        self.prompt = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                   left_margin=8, right_margin=8)
        self.prompt.connect("key-press-event", self._on_prompt_key)
        prompt_scroll = Gtk.ScrolledWindow(min_content_height=84, shadow_type=Gtk.ShadowType.IN)
        prompt_scroll.add(self.prompt)
        main.pack_start(prompt_scroll, False, False, 0)

        self.examples = Gtk.Box(spacing=6)
        self.examples.pack_start(label("Try:"), False, False, 0)
        for title, ex in EXAMPLES:
            b = Gtk.Button(label=title, tooltip_text=ex)
            b.connect("clicked", lambda _b, t=ex: self.prompt.get_buffer().set_text(t))
            self.examples.pack_start(b, False, False, 0)
        main.pack_start(self.examples, False, False, 0)

        row = Gtk.Box(spacing=10)
        self.generate_btn = Gtk.Button(label="Generate")
        self.generate_btn.get_style_context().add_class("suggested-action")
        self.generate_btn.connect("clicked", lambda *_: self.generate())
        self.spinner = Gtk.Spinner()
        self.status = label()
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_line_wrap(False)
        row.pack_start(self.generate_btn, False, False, 0)
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        main.pack_start(row, False, False, 0)

        # Preview area
        bg = Gtk.EventBox(name="preview-bg")
        # WebKit's transparent pixels don't blend with parent GTK widgets, so the preview
        # page gets an opaque backdrop matching the preview area.
        self.preview = WidgetView(app.cfg.get("developer_extras", False), background=PREVIEW_BG)
        self.preview.set_halign(Gtk.Align.CENTER)
        self.preview.set_valign(Gtk.Align.CENTER)
        self.preview.set_margin_top(24)
        self.preview.set_margin_bottom(24)
        self.preview_hint = label("Your widget preview appears here.")
        self.preview_hint.set_halign(Gtk.Align.CENTER)
        self.preview_hint.get_style_context().add_class("dim")
        stack_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        stack_box.set_valign(Gtk.Align.CENTER)
        stack_box.set_halign(Gtk.Align.CENTER)
        stack_box.pack_start(self.preview, False, False, 0)
        stack_box.pack_start(self.preview_hint, False, False, 0)
        bg.add(stack_box)
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.add(bg)
        main.pack_start(preview_scroll, True, True, 0)

        self.info = label()
        self.info.get_style_context().add_class("dim")
        main.pack_start(self.info, False, False, 0)

        actions = Gtk.Box(spacing=8)
        self.place_btn = Gtk.Button(label="Place on desktop")
        self.place_btn.get_style_context().add_class("suggested-action")
        self.place_btn.connect("clicked", lambda *_: self.place())
        self.commands_btn = Gtk.Button(label="Review commands…")
        self.commands_btn.connect("clicked", lambda *_: self._review_draft_commands())
        self.discard_btn = Gtk.Button(label="Discard")
        self.discard_btn.connect("clicked", lambda *_: self.reset_editor())
        actions.pack_end(self.place_btn, False, False, 0)
        actions.pack_end(self.discard_btn, False, False, 0)
        actions.pack_start(self.commands_btn, False, False, 0)
        main.pack_start(actions, False, False, 0)

        self.show_all()
        self.refresh_list()
        self.reset_editor()

    # --- editor state -------------------------------------------------------
    def reset_editor(self):
        if self.busy:
            return
        self.draft, self.draft_approved, self.editing_id, self.prompts = None, False, None, []
        self.auto_place = False
        self.prompt.get_buffer().set_text("")
        self.preview.load_widget("<html><body style='background:transparent'></body></html>", {}, False)
        self.preview.set_size_request(1, 1)
        self.preview.hide()
        self.preview_hint.show()
        self.examples.show()
        self._sync_ui()
        self.status.set_text("")
        self.info.set_text("")
        self.prompt.grab_focus()

    def edit(self, widget_id: str):
        if self.busy:
            return
        manifest = store.load(widget_id)
        self.editing_id = widget_id
        self.draft = store.to_spec(manifest)
        self.draft_approved = store.is_approved(manifest)
        self.prompts = []
        self.prompt.get_buffer().set_text("")
        self._show_preview()
        self.status.set_text("Describe what to change, then press Refine.")
        self.present()
        self.prompt.grab_focus()

    def _sync_ui(self):
        has = self.draft is not None
        if self.editing_id:
            self.mode_label.set_markup(f"<big><b>Editing: {GLib.markup_escape_text(self.draft['name'])}</b></big>")
        elif has:
            self.mode_label.set_markup(f"<big><b>Draft: {GLib.markup_escape_text(self.draft['name'])}</b></big>")
        else:
            self.mode_label.set_markup("<big><b>Describe your widget</b></big>")
        self.generate_btn.set_label("Refine" if has else "Generate")
        self.place_btn.set_label("Save changes" if self.editing_id else "Place on desktop")
        self.place_btn.set_sensitive(has and not self.busy)
        self.discard_btn.set_sensitive(has and not self.busy)
        self.generate_btn.set_sensitive(not self.busy)
        self.commands_btn.set_visible(has and bool(self.draft.get("commands")))
        self.examples.set_visible(not has)

    def _show_preview(self):
        spec = self.draft
        self.preview_hint.hide()
        self.preview.show()
        self.preview.set_size_request(spec["width"], spec["height"])
        self.preview.load_widget(spec["html"], spec["commands"], self.draft_approved)
        n = len(spec["commands"])
        if n:
            state = "approved" if self.draft_approved else "NOT approved — preview shows no live data"
            self.info.set_text(f"{spec['width']}×{spec['height']} · {spec['position']} · "
                               f"{n} shell command{'s' if n != 1 else ''} ({state})")
        else:
            self.info.set_text(f"{spec['width']}×{spec['height']} · {spec['position']} · no shell commands")
        self._sync_ui()

    # --- generation ------------------------------------------------------------
    def _on_prompt_key(self, _w, event):
        from gi.repository import Gdk
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.generate()
            return True
        return False

    def set_prompt(self, text: str):
        self.prompt.get_buffer().set_text(text)

    def generate(self):
        buf = self.prompt.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text or self.busy:
            return
        self.busy = True
        current = self.draft
        cfg = dict(self.app.cfg)
        self.spinner.start()
        self.status.set_text(f"{'Refining' if current else 'Generating'}… (this can take a minute)")
        self._sync_ui()

        def work():
            try:
                backend = backends.from_config(cfg)  # may probe for the CLI, so not on the UI thread
                GLib.idle_add(self.status.set_text, f"{'Refining' if current else 'Generating'} with "
                              f"{backend.name}… (this can take a minute)")
                spec = generator.generate(backend, text, current)
                GLib.idle_add(self._on_generated, text, spec, current)
            except Exception as e:  # surfaced to the user, not fatal
                GLib.idle_add(self._on_failed, str(e), isinstance(e, backends.SetupError))

        threading.Thread(target=work, daemon=True).start()

    def _on_generated(self, text, spec, previous):
        self.busy = False
        self.spinner.stop()
        prev_cmds = previous.get("commands") if previous else None
        if not spec["commands"]:
            self.draft_approved = True
        elif not (self.draft_approved and store.commands_hash(prev_cmds) == store.commands_hash(spec["commands"])):
            self.draft_approved = approval_dialog(self, spec["name"], spec["commands"])
        self.draft = spec
        self.prompts.append(text)
        self.prompt.get_buffer().set_text("")
        self._show_preview()
        self.status.set_text("Done. Refine it with another instruction, or place it on the desktop.")
        if self.auto_place:
            self.place()
        return False

    def _on_failed(self, message, needs_setup=False):
        self.busy = False
        self.auto_place = False
        self.spinner.stop()
        self.status.set_text("Generation failed.")
        self._sync_ui()
        title = "Connect Pickit to Claude" if needs_setup else "Could not generate the widget"
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.CLOSE, text=title)
        dlg.format_secondary_text(message)
        if needs_setup:
            dlg.add_button("Open Settings", Gtk.ResponseType.ACCEPT)
        response = dlg.run()
        dlg.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            self._on_settings(None)
        return False

    def _review_draft_commands(self):
        if self.draft and self.draft["commands"]:
            self.draft_approved = approval_dialog(self, self.draft["name"], self.draft["commands"])
            self._show_preview()

    def place(self):
        if not self.draft:
            return
        manifest = store.save_spec(self.draft, self.editing_id, approved=self.draft_approved,
                                   prompt=" → ".join(self.prompts) or None)
        if not self.draft_approved:
            manifest.pop("approved_hash", None)
        manifest["enabled"] = True
        store.save_manifest(manifest)  # the desktop daemon picks this up
        autostart.ensure_daemon()
        self.refresh_list()
        name = manifest["name"]
        self.reset_editor()
        self.status.set_text(f"“{name}” is on your desktop. Alt+drag to move it; right-click for options.")

    # --- sidebar ----------------------------------------------------------------
    def refresh_list(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        widgets = store.list_widgets()
        if not widgets:
            empty = label("No widgets yet.")
            empty.get_style_context().add_class("dim")
            self.listbox.add(empty)
        for m in widgets:
            row = Gtk.Box(spacing=6, border_width=4)
            name = Gtk.Label(label=m["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            name.set_tooltip_text(" → ".join(m.get("history", [])) or m["name"])
            switch = Gtk.Switch(active=m.get("enabled", True), valign=Gtk.Align.CENTER)
            switch.set_tooltip_text("Show on desktop")
            switch.connect("notify::active", lambda s, _p, wid=m["id"]: self.set_enabled(wid, s.get_active()))
            edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
            edit.set_tooltip_text("Edit with AI")
            edit.connect("clicked", lambda _b, wid=m["id"]: self.edit(wid))
            delete = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
            delete.set_tooltip_text("Delete")
            delete.connect("clicked", lambda _b, wid=m["id"]: self.delete_widget(wid))
            for b in (edit, delete):
                b.get_style_context().add_class("flat")
            row.pack_start(name, True, True, 0)
            row.pack_start(switch, False, False, 0)
            row.pack_start(edit, False, False, 0)
            row.pack_start(delete, False, False, 0)
            self.listbox.add(row)
        self.listbox.show_all()

    def set_enabled(self, widget_id: str, enabled: bool):
        manifest = store.load(widget_id)
        if manifest.get("enabled", True) != enabled:
            manifest["enabled"] = enabled
            store.save_manifest(manifest)
            autostart.ensure_daemon()

    def delete_widget(self, widget_id: str):
        manifest = store.load(widget_id)
        if not confirm(self, f"Delete “{manifest['name']}”?"):
            return
        store.delete(widget_id)
        if self.editing_id == widget_id:
            self.editing_id = None
            self.reset_editor()

    # --- settings ---------------------------------------------------------------
    def _on_backend_changed(self, combo):
        self.app.cfg["backend"] = combo.get_active_id()
        config.save(self.app.cfg)

    def _on_settings(self, _btn):
        dlg = SettingsDialog(self, self.app.cfg)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.apply(self.app.cfg)
            config.save(self.app.cfg)
            self.backend_combo.set_active_id(self.app.cfg["backend"])
        dlg.destroy()


class PickitApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = config.load()
        self.maker: MakerWindow | None = None
        self._monitor = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        install_css()
        Gtk.Window.set_default_icon_from_file(str(autostart.DATA_FILES / f"{APP_ID}.svg"))
        autostart.install_launcher()
        autostart.ensure_daemon()
        # Refresh the sidebar when the daemon hides/deletes widgets from their menus.
        self._monitor = store.watch(lambda: self.maker and self.maker.refresh_list())

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        command = args[0] if args else "gui"
        maker = self.show_maker()
        if command == "new" and len(args) > 1:
            maker.reset_editor()
            maker.set_prompt(" ".join(args[1:]))
            maker.auto_place = True
            maker.generate()
        elif command == "edit" and len(args) > 1:
            try:
                maker.edit(args[1])
            except FileNotFoundError:
                pass
        return 0

    def show_maker(self) -> MakerWindow:
        if not self.maker:
            self.maker = MakerWindow(self)
            self.maker.connect("destroy", self._on_maker_destroyed)
        self.maker.present()
        return self.maker

    def _on_maker_destroyed(self, *_):
        self.maker = None
