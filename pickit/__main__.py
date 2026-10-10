"""Entry point.

    python -m pickit              open the maker window
    python -m pickit new "..."    generate a widget from a description and place it
    python -m pickit edit <id>    open a widget in the maker window
    python -m pickit gallery      browse ready-made widgets
    python -m pickit list         list saved widgets
    python -m pickit export <id> [FILE]
                                  save a widget as a .pickit file to share it
    python -m pickit import FILE  open a .pickit file (you approve its commands first)
    python -m pickit run          start the desktop daemon that shows the widgets
                                       (started automatically at login and by the maker)
    python -m pickit stop         stop the desktop daemon (widgets disappear until next start)
"""

import os
import sys
from pathlib import Path


def main() -> int:
    # WebKit's GPU buffer sharing (DMABuf/GBM) fails on NVIDIA's driver, especially in
    # sandboxes, leaving widgets invisible. Hand frames over through shared memory instead.
    # (Not WEBKIT_DISABLE_DMABUF_RENDERER: with WebKit 2.54+, as in the Flatpak runtime,
    # that legacy path mis-draws composited layers such as shadows and animations.)
    os.environ.setdefault("WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1")
    args = sys.argv[1:]
    if args and args[0] in ("-V", "--version"):
        from . import __version__
        print(f"pickit {__version__}")
        return 0
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if args and args[0] == "list":
        from . import store
        widgets = store.list_widgets()
        for m in widgets:
            state = "on " if m.get("enabled", True) else "off"
            cmds = len(m.get("commands", {}))
            approved = "" if store.is_approved(m) else "  [commands not approved]"
            print(f"[{state}] {m['id']:<40} {m['name']}  ({cmds} commands){approved}")
        if not widgets:
            print("No widgets yet. Run: python -m pickit")
        return 0
    if args and args[0] == "export":
        return _export(args[1:])
    # Everything below opens windows. (The commands above work without GTK installed.)
    if args and args[0] in ("run", "stop"):
        from gi.repository import GLib
        # The X11 WM_CLASS of the widget windows (set before GTK starts). Not "pickit": that class
        # belongs to the launcher (StartupWMClass), and docks such as Plank would show widgets
        # as a running app.
        GLib.set_prgname("pickit-widget")
        if args[0] == "run":
            from . import session
            session.setup_widget_display()  # Wayland layer-shell if the compositor has it, else X11
        from .daemon import DesktopDaemon, acquire_instance_lock, is_running, replace_older_daemon
        if args[0] == "stop" and not is_running():
            print("The desktop daemon is not running.")
            return 0
        if args[0] == "run" and not acquire_instance_lock() and not replace_older_daemon():
            print("pickit: a widget daemon is already running")
            return 0
        return DesktopDaemon().run(sys.argv)
    if args and args[0] not in ("new", "edit", "gui", "gallery", "import") and not Path(args[0]).is_file():
        print(f"Unknown command: {args[0]}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2
    if args and args[0] == "import" and len(args) < 2:
        print("Usage: pickit import FILE", file=sys.stderr)
        return 2

    # The Pickit window is an ordinary app window: native Wayland on Wayland, X11 on X11.
    from gi.repository import GLib
    GLib.set_prgname("pickit")  # WM_CLASS on X11, so the launcher/taskbar icon matches

    from .app import PickitApp
    return PickitApp().run(sys.argv)


def _export(args) -> int:
    from . import share, store
    if not args:
        print("Usage: pickit export <id> [FILE]   (ids: pickit list)", file=sys.stderr)
        return 2
    try:
        manifest = store.load(args[0])
    except FileNotFoundError:
        print(f"No widget with the id {args[0]}. See: pickit list", file=sys.stderr)
        return 1
    path = Path(args[1]) if len(args) > 1 else Path.cwd() / share.default_filename(manifest["name"])
    try:
        share.export_widget(args[0], path)
    except OSError as e:
        print(f"Could not write {path}: {e}\n(In the Flatpak, export from the Pickit window instead: "
              "it can save anywhere.)", file=sys.stderr)
        return 1
    print(f"Exported “{manifest['name']}” to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
