"""The desktop daemon: owns every widget window, independent of the maker app.

It runs as its own unique process (`python -m pickit run`), started at login
and by the maker app, and keeps running with or without the maker window. It
watches the widget store and reconciles its windows whenever anything changes.
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, autostart, config, runtime, store, theme  # noqa: E402
from .dialogs import approval_dialog, confirm, export_dialog, install_css  # noqa: E402
from .events import SystemEvents  # noqa: E402
from .widget_window import WidgetWindow, dialog_parent, layer_shell  # noqa: E402

# Must be prefixed by the app ID: Flatpak only lets an app own names under its ID.
DAEMON_ID = runtime.APP_ID + ".Desktop"


_lock_file = None


def acquire_instance_lock() -> bool:
    """Only one widget daemon may run, whichever package (source, Flatpak, AppImage) or
    app ID started it; otherwise every widget would be drawn twice. The lock lives in the
    shared data directory and is released automatically when the process exits."""
    global _lock_file
    import fcntl
    if _lock_file is not None:
        return True
    store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Not "w": that would empty the running daemon's version before we know it's running.
    lock = open(store.DATA_DIR / "daemon.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return False
    lock.truncate(0)
    lock.write(__version__)  # for running_version(): an update replaces an older daemon
    lock.flush()
    _lock_file = lock  # keep the file open (and locked) for the life of the process
    return True


def running_version() -> str:
    """The version of the widget daemon that holds the lock ("" if it's from before 1.5.3,
    which didn't record it)."""
    try:
        return (store.DATA_DIR / "daemon.lock").read_text().strip()
    except OSError:
        return ""


def is_older(version: str, than: str) -> bool:
    """Whether `version` ("1.5.2"; "" for daemons before 1.5.3) is older than `than`."""
    def parts(v):
        return tuple(int(x) if x.isdigit() else 0 for x in v.split(".")) if v else ()
    return parts(version) < parts(than)


def replace_older_daemon() -> bool:
    """A daemon from another version still runs, typically the one started at login before
    Pickit was updated: it would keep running old code (1.5.2 moved approvals, so a 1.5.1
    daemon ran no commands at all). Stop it and take over. True if the lock is now ours."""
    import subprocess
    import time
    old = running_version()
    if not is_older(old, __version__):
        return False  # the same version, or a newer one (e.g. an older AppImage next to the Flatpak)
    print(f"pickit: replacing the widget daemon from Pickit {old or 'an earlier version'}", flush=True)
    try:  # `pickit stop`, answered by the running daemon whatever its version
        subprocess.run([sys.executable, "-m", "pickit", "stop"], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for _ in range(100):  # until it has exited and released the lock
        if acquire_instance_lock():
            return True
        time.sleep(0.1)
    print("pickit: the old widget daemon didn't stop", flush=True)
    return False


def is_running() -> bool:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "NameHasOwner", GLib.Variant("(s)", (DAEMON_ID,)), GLib.VariantType("(b)"),
                          Gio.DBusCallFlags.NONE, -1, None)
    return reply.unpack()[0]


class DesktopDaemon(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=DAEMON_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.windows: dict[str, WidgetWindow] = {}
        self._monitor = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        install_css()
        print(f"pickit: widgets are {'Wayland layer-shell surfaces' if layer_shell() else 'X11 windows'}",
              flush=True)  # in daemon.log, for bug reports
        self.hold()  # stay alive even with zero widgets, so new ones appear immediately
        cfg = config.load()
        if cfg.get("autostart", True):
            autostart.set_enabled(True, cfg.get("autostart_command", ""))  # also refreshes a moved path
        self._monitor = store.watch(self.reconcile)
        self._events = SystemEvents(self.refresh_all)
        self._theme = None
        # Themes that follow the desktop's light/dark mode or accent color restyle live.
        theme.watch_system(lambda: GLib.idle_add(lambda: self.reconcile() and False))
        display = Gdk.Display.get_default()
        self._monitor_timer = 0
        for signal in ("monitor-added", "monitor-removed"):
            display.connect(signal, lambda *_: self._monitors_changed())
        self.reconcile()

    def _on_window_destroyed(self, win, wid):
        if self.windows.get(wid) is not win:
            return  # reconcile() closed it on purpose
        # Closed from outside: on Wayland the compositor closes layer surfaces whose output
        # was unplugged. Bring the widget back on a monitor that's still there.
        self.windows.pop(wid)
        GLib.timeout_add(500, lambda: self.reconcile() and False)

    def _monitors_changed(self):
        """A monitor was plugged in or removed: place every widget again, once things settle."""
        if self._monitor_timer:
            GLib.source_remove(self._monitor_timer)

        def replace():
            self._monitor_timer = 0
            for wid, win in list(self.windows.items()):
                try:
                    manifest = store.load(wid)
                except FileNotFoundError:
                    continue
                win.apply_manifest(manifest, reposition="x" not in manifest)
            return False
        self._monitor_timer = GLib.timeout_add(800, replace)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if args and args[0] == "stop":
            self.quit()
        return 0

    def refresh_all(self, reason):
        """A system event happened: fetch fresh data now instead of on the next timer.

        Power changes only affect fast-changing data; after waking up or a network
        change even slow data (weather, IP address) is stale, so everything refreshes.
        """
        max_interval = 300 if reason == "power" else None
        for win in self.windows.values():
            win.view.refresh(max_interval)

    def reconcile(self):
        cfg = config.load()
        tokens = theme.current(cfg.get("theme"))
        if tokens != self._theme:
            self._theme = tokens
            for win in self.windows.values():
                win.set_theme(tokens)
        wanted = {m["id"]: m for m in store.list_widgets() if m.get("enabled", True)}
        for wid in list(self.windows):
            if wid not in wanted:
                self.windows.pop(wid).destroy()
        for wid, manifest in wanted.items():
            win = self.windows.get(wid)
            if win is None:
                win = WidgetWindow(manifest, cfg, self._callbacks(), theme=tokens)
                win.connect("destroy", self._on_window_destroyed, wid)
                self.windows[wid] = win
                self.add_window(win)
                win.show_all()
            else:
                win.lock_all = cfg.get("lock_widgets", False)
                win.update_flags(manifest)
                if win.signature != store.signature(manifest):
                    win.apply_manifest(manifest, reposition="x" not in manifest)

    # --- widget context-menu actions ------------------------------------------
    def _callbacks(self):
        return {"edit": lambda wid: autostart.spawn("edit", wid),
                "approve": self._review_commands,
                "export": lambda wid: export_dialog(None, wid),
                "hide": self._hide,
                "delete": self._delete}

    def _hide(self, wid):
        manifest = store.load(wid)
        manifest["enabled"] = False
        store.save_manifest(manifest)  # the watcher closes the window

    def _review_commands(self, wid):
        manifest = store.load(wid)
        parent = dialog_parent(self.windows.get(wid))
        if approval_dialog(parent, manifest["name"], manifest.get("commands", {})):
            store.approve(manifest, "reviewed")
        else:
            store.revoke(wid)

    def _delete(self, wid):
        manifest = store.load(wid)
        if confirm(dialog_parent(self.windows.get(wid)), f"Delete “{manifest['name']}”?"):
            store.delete(wid)
