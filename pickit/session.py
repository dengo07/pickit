"""Which display system the desktop widgets use.

- On Wayland compositors with the layer-shell protocol (KDE Plasma, Hyprland, Sway, COSMIC,
  niri, labwc, ...), widgets are native layer surfaces in the "bottom" layer: above the
  wallpaper, below every window, never in a taskbar.
- Everywhere else (X11 sessions; GNOME and Cinnamon on Wayland, which don't offer
  layer-shell), they are X11 windows with dock/keep-below hints, through XWayland on Wayland.

`PICKIT_WIDGET_BACKEND=x11|layer-shell` overrides the choice.
"""

import os
import sys

X11, LAYER_SHELL = "x11", "layer-shell"


def preferred(env=os.environ) -> str:
    """The backend to try, from the environment alone."""
    forced = env.get("PICKIT_WIDGET_BACKEND", "").strip().lower()
    if forced in (X11, LAYER_SHELL):
        return forced
    if env.get("GDK_BACKEND", "").startswith("x11"):  # the user (or our own fallback) asked for X11
        return X11
    return LAYER_SHELL if env.get("WAYLAND_DISPLAY") else X11


def layer_shell_supported() -> bool:
    """Connects GTK to the display, so call it after GDK_BACKEND is decided."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import Gdk, GtkLayerShell
    except (ImportError, ValueError):
        return False
    display = Gdk.Display.get_default()
    return (display is not None and "Wayland" in type(display).__name__
            and hasattr(GtkLayerShell, "is_supported")  # gtk-layer-shell >= 0.6
            and bool(GtkLayerShell.is_supported()))


def setup_widget_display() -> str:
    """Pick the widget daemon's display backend before GTK starts. May restart the process in
    X11 mode if the Wayland compositor turns out not to support layer-shell."""
    if preferred() == LAYER_SHELL:
        os.environ["GDK_BACKEND"] = "wayland"
        if layer_shell_supported():
            return LAYER_SHELL
        # GTK is already connected to Wayland, so start over as an X11 (XWayland) client.
        os.environ.update(GDK_BACKEND="x11", PICKIT_WIDGET_BACKEND=X11)
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])
    os.environ["GDK_BACKEND"] = "x11"
    return X11
