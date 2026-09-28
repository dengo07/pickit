"""The widget theme: one palette, corner radius and font that every themed widget follows.

Widgets use it through tokens: `{theme.accent}` in native widgets (a built-in data source,
like `now`), `var(--pickit-accent)` in HTML widgets. A widget counts as *themed* if it uses any
token; widgets made before themes existed keep their own look (see `is_themed`).

The settings live in config["theme"]: {"preset", "mode": "dark"|"light"|"system",
"overrides": {token: color}, "radius", "font", "system_accent"}.
"""

import json

TOKENS = ("accent", "text", "muted", "card", "border", "good", "warn", "bad")
LABELS = {"accent": "Accent", "text": "Text", "muted": "Secondary text", "card": "Card",
          "border": "Card border", "good": "Good", "warn": "Warning", "bad": "Critical"}

# Each preset has a dark and a light variant. Charcoal/dark is exactly the look Pickit had
# before themes, so nothing changes until the user picks something else.
PRESETS = {
    "charcoal": {
        "name": "Charcoal",
        "dark": {"accent": "#f0a64a", "text": "#f4f1ea", "muted": "rgba(244,241,234,0.62)",
                 "card": "rgba(18,18,24,0.78)", "border": "rgba(255,255,255,0.08)",
                 "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171"},
        "light": {"accent": "#c2701a", "text": "#1d1d1f", "muted": "rgba(29,29,31,0.6)",
                  "card": "rgba(250,248,244,0.88)", "border": "rgba(0,0,0,0.08)",
                  "good": "#15803d", "warn": "#b45309", "bad": "#dc2626"},
    },
    "graphite": {
        "name": "Graphite",
        "dark": {"accent": "#5b9bd5", "text": "#e8eaed", "muted": "rgba(232,234,237,0.6)",
                 "card": "rgba(30,32,36,0.84)", "border": "rgba(255,255,255,0.07)",
                 "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171"},
        "light": {"accent": "#2f6fb0", "text": "#1f2328", "muted": "rgba(31,35,40,0.6)",
                  "card": "rgba(244,245,247,0.9)", "border": "rgba(0,0,0,0.08)",
                  "good": "#15803d", "warn": "#b45309", "bad": "#dc2626"},
    },
    "forest": {
        "name": "Forest",
        "dark": {"accent": "#e0a458", "text": "#eef3ee", "muted": "rgba(238,243,238,0.62)",
                 "card": "rgba(20,34,28,0.84)", "border": "rgba(255,255,255,0.07)",
                 "good": "#86efac", "warn": "#fcd34d", "bad": "#fca5a5"},
        "light": {"accent": "#9a5b12", "text": "#1e2b22", "muted": "rgba(30,43,34,0.62)",
                  "card": "rgba(240,245,238,0.9)", "border": "rgba(0,0,0,0.08)",
                  "good": "#15803d", "warn": "#a16207", "bad": "#b91c1c"},
    },
    "paper": {
        "name": "Paper",
        "dark": {"accent": "#e5a54b", "text": "#f3ede2", "muted": "rgba(243,237,226,0.6)",
                 "card": "rgba(40,36,31,0.86)", "border": "rgba(255,255,255,0.07)",
                 "good": "#86efac", "warn": "#fcd34d", "bad": "#fca5a5"},
        "light": {"accent": "#b4541f", "text": "#2b2a28", "muted": "rgba(43,42,40,0.6)",
                  "card": "rgba(252,249,242,0.92)", "border": "rgba(60,50,30,0.1)",
                  "good": "#3f7d20", "warn": "#a16207", "bad": "#b42318"},
    },
}
DEFAULT = {"preset": "charcoal", "mode": "dark", "overrides": {}, "radius": 16, "font": "",
           "system_accent": False}


def settings(cfg_theme: dict | None) -> dict:
    """The theme settings with defaults filled in and nonsense dropped."""
    s = {**DEFAULT, **(cfg_theme or {})}
    if s["preset"] not in PRESETS:
        s["preset"] = DEFAULT["preset"]
    if s["mode"] not in ("dark", "light", "system"):
        s["mode"] = "dark"
    s["overrides"] = {k: v for k, v in (s.get("overrides") or {}).items() if k in TOKENS and isinstance(v, str)}
    try:
        s["radius"] = max(0, min(40, int(s["radius"])))
    except (TypeError, ValueError):
        s["radius"] = DEFAULT["radius"]
    s["font"] = s["font"] if isinstance(s["font"], str) else ""
    return s


def tokens(cfg_theme: dict | None = None, system_dark: bool | None = None,
           system_accent: str | None = None) -> dict:
    """The active theme: every token's color, plus "radius", "font" and "mode" (dark/light)."""
    s = settings(cfg_theme)
    dark = s["mode"] == "dark" or (s["mode"] == "system" and system_dark is not False)
    palette = dict(PRESETS[s["preset"]]["dark" if dark else "light"])
    if s["system_accent"] and system_accent:
        palette["accent"] = system_accent
    palette.update(s["overrides"])
    return {**palette, "radius": s["radius"], "font": s["font"], "mode": "dark" if dark else "light"}


def current(cfg_theme: dict | None) -> dict:
    """The active theme, asking the desktop only when the theme follows it."""
    s = settings(cfg_theme)
    if s["mode"] == "system" or s["system_accent"]:
        return tokens(s, *system_appearance())
    return tokens(s)


def default_tokens() -> dict:
    return tokens(None)


def is_themed(ui) -> bool:
    """Whether a native component tree uses the theme (made with 1.5.0 or later)."""
    return "{theme." in json.dumps(ui)


def css_variables(t: dict) -> str:
    """The theme as CSS custom properties, for HTML widgets."""
    lines = [f"--pickit-{k}: {t[k]};" for k in TOKENS]
    lines.append(f"--pickit-radius: {int(t['radius'])}px;")
    if t.get("font"):
        lines.append(f"--pickit-font: \"{t['font']}\";")
    return ":root { " + " ".join(lines) + " }"


# --- the desktop's own light/dark mode and accent color (XDG settings portal) -------------------
_PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
           "org.freedesktop.portal.Settings")


def _read_portal(key: str):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    for method in ("ReadOne", "Read"):  # ReadOne is newer; Read wraps the value twice
        try:
            reply = bus.call_sync(*_PORTAL, method, GLib.Variant("(ss)", ("org.freedesktop.appearance", key)),
                                  None, Gio.DBusCallFlags.NONE, 500, None)
        except GLib.Error:
            continue
        value = reply.unpack()[0]
        while isinstance(value, GLib.Variant):
            value = value.unpack()
        return value
    return None


def system_appearance() -> tuple[bool | None, str | None]:
    """(prefers dark?, accent color as #rrggbb), each None if the desktop doesn't say."""
    dark = accent = None
    try:
        scheme = _read_portal("color-scheme")  # 1 = dark, 2 = light, 0 = no preference
        dark = {1: True, 2: False}.get(scheme)
        rgb = _read_portal("accent-color")
        if isinstance(rgb, tuple) and len(rgb) == 3 and all(0 <= c <= 1 for c in rgb):
            accent = "#" + "".join(f"{round(c * 255):02x}" for c in rgb)
    except Exception:  # no D-Bus, no portal: fall back below
        pass
    if dark is None:
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            gtk = Gtk.Settings.get_default()
            if gtk is not None:
                dark = bool(gtk.props.gtk_application_prefer_dark_theme
                            or "dark" in (gtk.props.gtk_theme_name or "").lower())
        except (ImportError, ValueError):
            pass
    return dark, accent


def watch_system(callback):
    """Call `callback()` when the desktop switches light/dark mode or accent color."""
    from gi.repository import Gio
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        return None

    def on_signal(_bus, _sender, _path, _iface, _signal, params):
        namespace, key, _value = params.unpack()
        if namespace == "org.freedesktop.appearance" and key in ("color-scheme", "accent-color"):
            callback()
    return bus.signal_subscribe(_PORTAL[0], _PORTAL[2], "SettingChanged", _PORTAL[1], None,
                                Gio.DBusSignalFlags.NONE, on_signal)
