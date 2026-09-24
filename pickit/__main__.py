"""Entry point.

    python -m pickit              open the maker window
    python -m pickit new "..."    generate a widget from a description and place it
    python -m pickit edit <id>    open a widget in the maker window
    python -m pickit list         list saved widgets
    python -m pickit run          start the desktop daemon that shows the widgets
                                       (started automatically at login and by the maker)
    python -m pickit stop         stop the desktop daemon (widgets disappear until next start)
"""

import os
import sys


def main() -> int:
    # Widgets rely on X11 window hints (keep-below, sticky, dock layer). On Wayland
    # desktops this runs the app through XWayland, where those hints still apply.
    os.environ.setdefault("GDK_BACKEND", "x11")
    # WebKit's GPU buffer sharing (DMABuf/GBM) fails on NVIDIA's driver, especially in
    # sandboxes, leaving widgets invisible. Hand frames over through shared memory instead.
    # (Not WEBKIT_DISABLE_DMABUF_RENDERER: with WebKit 2.54+, as in the Flatpak runtime,
    # that legacy path mis-draws composited layers such as shadows and animations.)
    os.environ.setdefault("WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1")
    from gi.repository import GLib
    GLib.set_prgname("pickit")  # WM_CLASS, so the launcher/taskbar icon matches
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
    if args and args[0] in ("run", "stop"):
        from .daemon import DesktopDaemon, acquire_instance_lock, is_running
        if args[0] == "stop" and not is_running():
            print("The desktop daemon is not running.")
            return 0
        if args[0] == "run" and not acquire_instance_lock():
            print("pickit: a widget daemon is already running")
            return 0
        return DesktopDaemon().run(sys.argv)
    if args and args[0] not in ("new", "edit", "gui"):
        print(f"Unknown command: {args[0]}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2

    from .app import PickitApp
    return PickitApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
