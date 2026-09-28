"""The widget theme: presets, resolution, light/dark, and which widgets follow it."""

import json
from pathlib import Path

import pytest

from pickit import gallery, theme
from pickit.native.spec import SAFE_CSS


@pytest.mark.parametrize("preset", list(theme.PRESETS))
def test_presets_are_complete_and_safe(preset):
    for variant in ("dark", "light"):
        palette = theme.PRESETS[preset][variant]
        assert set(palette) == set(theme.TOKENS), (preset, variant)
        assert all(SAFE_CSS.match(color) for color in palette.values())


def test_default_is_the_classic_look():
    t = theme.tokens()
    assert t == {**theme.PRESETS["charcoal"]["dark"], "radius": 16, "font": "", "mode": "dark"}
    assert t["card"] == "rgba(18,18,24,0.78)"   # the card default before themes existed


def test_modes():
    assert theme.tokens({"mode": "light"})["mode"] == "light"
    assert theme.tokens({"mode": "system"}, system_dark=False)["mode"] == "light"
    assert theme.tokens({"mode": "system"}, system_dark=True)["mode"] == "dark"
    assert theme.tokens({"mode": "system"}, system_dark=None)["mode"] == "dark"   # unknown: dark


def test_overrides_and_system_accent():
    assert theme.tokens({"overrides": {"accent": "#123456", "bogus": "x"}})["accent"] == "#123456"
    assert theme.tokens({"system_accent": True}, system_accent="#3584e4")["accent"] == "#3584e4"
    assert theme.tokens({"system_accent": False}, system_accent="#3584e4")["accent"] == "#f0a64a"
    # a color the user picked wins over the desktop's
    assert theme.tokens({"system_accent": True, "overrides": {"accent": "#111111"}},
                        system_accent="#3584e4")["accent"] == "#111111"


def test_settings_are_sanitized():
    s = theme.settings({"preset": "nope", "mode": "sideways", "radius": 99, "font": 7})
    assert (s["preset"], s["mode"], s["radius"], s["font"]) == ("charcoal", "dark", 40, "")
    assert theme.settings({"radius": "x"})["radius"] == 16


def test_which_widgets_are_themed():
    assert theme.is_themed({"type": "label", "color": "{theme.text}"})
    assert not theme.is_themed({"type": "label", "color": "#ffffff", "text": "{now|time:%H}"})


def test_css_variables():
    css = theme.css_variables(theme.tokens({"font": "Inter", "radius": 8}))
    assert "--pickit-accent: #f0a64a;" in css and "--pickit-radius: 8px;" in css
    assert '--pickit-font: "Inter";' in css
    assert "--pickit-font" not in theme.css_variables(theme.tokens())


def test_gallery_and_examples_follow_the_theme():
    for item in gallery.items():
        assert theme.is_themed(item.spec["ui"]), item.id
    for path in (Path(theme.__file__).parent / "prompts" / "native_examples").glob("*.json"):
        assert theme.is_themed(json.loads(path.read_text())["ui"]), path.name
