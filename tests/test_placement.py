"""Widget placement (X11 coordinates and Wayland layer-shell anchors) and the display choice."""

import os

import pytest

from pickit import placement, session
from pickit.placement import MARGIN

AREA = (0, 30, 1920, 1010)   # a work area below a 30 px top panel
SCREEN, SIZE = (1920, 1080), (300, 120)


@pytest.mark.parametrize("position, xy", [
    ("top-left", (MARGIN, 30 + MARGIN)),
    ("top-right", (1920 - 300 - MARGIN, 30 + MARGIN)),
    ("bottom-center", ((1920 - 300) // 2, 30 + 1010 - 120 - MARGIN)),
    ("center", ((1920 - 300) // 2, 30 + (1010 - 120) // 2)),
    ("nonsense", (1920 - 300 - MARGIN, 30 + MARGIN)),   # unknown names fall back to top-right
])
def test_x11_coordinates(position, xy):
    assert placement.anchor_xy(position, AREA, *SIZE) == xy


@pytest.mark.parametrize("position, anchors", [
    ("top-left", {"top": MARGIN, "left": MARGIN}),
    ("bottom-right", {"bottom": MARGIN, "right": MARGIN}),
    ("top-center", {"top": MARGIN}),              # one edge: centered along it
    ("center-left", {"left": MARGIN}),
    ("center", {}),                               # no edge: centered on the screen
])
def test_layer_anchors(position, anchors):
    assert placement.layer_anchors(position) == anchors


def test_layer_anchors_and_x11_agree():
    """The same position lands in the same place with either display system."""
    full = (0, 0, *SCREEN)
    for position in ("top-left", "top-right", "top-center", "center-left", "center", "center-right",
                     "bottom-left", "bottom-center", "bottom-right"):
        layer = placement.layer_top_left(placement.layer_anchors(position), SCREEN, SIZE)
        assert layer == placement.anchor_xy(position, full, *SIZE), position


def test_moved_widgets_are_pinned_by_their_corner():
    assert placement.layer_moved(300, 200) == {"top": 200, "left": 300}
    assert placement.layer_moved(-5, 7.6) == {"top": 7, "left": 0}
    assert placement.layer_top_left({"top": 200, "left": 300}, SCREEN, SIZE) == (300, 200)


def test_clamp_keeps_widgets_on_screen():
    assert placement.clamp(-40, 50, SCREEN, SIZE) == (0, 50)
    assert placement.clamp(5000, 5000, SCREEN, SIZE) == (1920 - 300, 1080 - 120)


@pytest.mark.parametrize("env, expected", [
    ({}, "x11"),                                                     # X11 session
    ({"WAYLAND_DISPLAY": "wayland-0"}, "layer-shell"),               # Wayland: try layer-shell
    ({"WAYLAND_DISPLAY": "wayland-0", "GDK_BACKEND": "x11"}, "x11"),  # asked for X11
    ({"WAYLAND_DISPLAY": "wayland-0", "PICKIT_WIDGET_BACKEND": "x11"}, "x11"),
    ({"PICKIT_WIDGET_BACKEND": "Layer-Shell"}, "layer-shell"),
    ({"WAYLAND_DISPLAY": "wayland-0", "PICKIT_WIDGET_BACKEND": "bogus"}, "layer-shell"),
])
def test_preferred_backend(env, expected):
    assert session.preferred(env) == expected


def test_falls_back_to_x11_without_layer_shell(monkeypatch):
    """On GNOME or Cinnamon (Wayland, no layer-shell) the daemon restarts itself as an X11 client."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("GDK_BACKEND", "")   # setenv, so the values the code sets get undone
    monkeypatch.setenv("PICKIT_WIDGET_BACKEND", "")
    monkeypatch.setattr(session, "layer_shell_supported", lambda: False)
    restarted = []
    monkeypatch.setattr(os, "execv", lambda exe, argv: restarted.append(argv))
    session.setup_widget_display()
    assert restarted, "should restart"
    assert os.environ["GDK_BACKEND"] == "x11" and os.environ["PICKIT_WIDGET_BACKEND"] == "x11"


def test_uses_layer_shell_when_supported(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("GDK_BACKEND", "")   # setenv, so the values the code sets get undone
    monkeypatch.setenv("PICKIT_WIDGET_BACKEND", "")
    monkeypatch.setattr(session, "layer_shell_supported", lambda: True)
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("should not restart"))
    assert session.setup_widget_display() == "layer-shell"
    assert os.environ["GDK_BACKEND"] == "wayland"


def test_x11_session_needs_no_probe(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    monkeypatch.setenv("GDK_BACKEND", "")
    monkeypatch.setenv("PICKIT_WIDGET_BACKEND", "")
    monkeypatch.setattr(session, "layer_shell_supported", lambda: pytest.fail("no Wayland to probe"))
    assert session.setup_widget_display() == "x11"
    assert os.environ["GDK_BACKEND"] == "x11"


@pytest.mark.parametrize("env, namespace", [
    ({"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "6"}, "dock"),   # survives Meta+D
    ({"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "5"}, "pickit-widget"),  # KWin 5 stacks docks on top
    ({"XDG_CURRENT_DESKTOP": "KDE"}, "pickit-widget"),
    ({"XDG_CURRENT_DESKTOP": "Hyprland"}, "pickit-widget"),
    ({}, "pickit-widget"),
])
def test_layer_namespace(env, namespace):
    widget_window = pytest.importorskip("pickit.widget_window")
    assert widget_window.layer_namespace(env) == namespace
