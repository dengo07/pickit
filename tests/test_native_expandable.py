import copy
import json
import re
from pathlib import Path

import pytest

from pickit import generator, store
from pickit.generator import SpecError
from pickit.native.spec import UISpecError, validate_ui

EXAMPLES = Path(__file__).parent.parent / "pickit" / "prompts" / "native_examples"
EXPANDABLE_EXAMPLES = ["system-details", "clock-agenda"]
SIZE = {"width": 300, "height": 200}


def load(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def expander(**extra):
    return {"type": "expander", "header": [{"type": "label", "text": "Head"}],
            "children": [{"type": "label", "text": "Body"}], **extra}


# --- the shipped examples ---------------------------------------------------------------
@pytest.mark.parametrize("name", EXPANDABLE_EXAMPLES)
def test_expandable_examples_validate(name):
    spec = load(name)
    result = generator.validate(spec)
    assert result["engine"] == "native"
    assert result["expandable"] == spec["expandable"]
    # validate_ui directly, with the declared commands and expandable block
    validate_ui(spec["ui"], result["commands"], result["expandable"])


@pytest.mark.parametrize("name", EXPANDABLE_EXAMPLES)
def test_examples_need_their_expandable_block(name):
    spec = load(name)
    del spec["expandable"]
    with pytest.raises(SpecError, match="expandable"):
        generator.validate(spec)


@pytest.mark.parametrize("name", EXPANDABLE_EXAMPLES)
def test_examples_reject_unknown_expandable_keys(name):
    spec = load(name)
    spec["expandable"] = {**spec["expandable"], "depth": 3}
    with pytest.raises(SpecError):
        generator.validate(spec)


# --- hostile trees ----------------------------------------------------------------------
@pytest.mark.parametrize("tree, message", [
    # two expanders
    ({"type": "column", "children": [expander(), expander()]}, "only one expander"),
    # nested expander (in the expander's own body, and deeper in the tree)
    (expander(children=[expander()]), "only one expander"),
    ({"type": "column", "children": [{"type": "card", "children": [expander()]}]},
     "root or a direct child"),
    # a toggle button that also has an action
    ({"type": "column", "children": [
        expander(), {"type": "button", "text": "x", "toggle": True, "action": "go"}]}, "can't also have"),
    # a button with neither
    ({"type": "column", "children": [expander(), {"type": "button", "text": "x"}]}, '"action" is required'),
    # toggle needs an expander
    ({"type": "button", "text": "x", "toggle": True}, "needs an expander"),
    # unknown properties on the expander
    (expander(width_expanded=400), 'unknown property "width_expanded"'),
    (expander(script="alert(1)"), 'unknown property "script"'),
    # bad values
    (expander(animation="explode"), "must be one of"),
    (expander(trigger="hover"), "must be one of"),
    (expander(chevron="yes"), "expected true or false"),
    (expander(children="body"), "expected a list of components"),
    # sizes on the expander itself stay within the pixel bounds
    (expander(width=-1), "whole number of pixels"),
    (expander(height=100000), "whole number of pixels"),
])
def test_hostile_trees_are_rejected(tree, message):
    with pytest.raises(UISpecError, match=re.escape(message)):
        validate_ui(tree, {"go": {"cmd": "true", "interval": 0}}, SIZE)


def test_expander_without_expandable_is_rejected():
    with pytest.raises(UISpecError, match="needs the widget's"):
        validate_ui(expander(), {}, None)


def test_expandable_without_expander_is_rejected():
    with pytest.raises(UISpecError, match="no expander"):
        validate_ui({"type": "label", "text": "x"}, {}, SIZE)


def test_valid_expander_and_toggle_are_accepted():
    tree = {"type": "column", "children": [expander(), {"type": "button", "text": "More", "toggle": True}]}
    assert validate_ui(tree, {}, SIZE) is tree


# --- hostile expandable blocks ----------------------------------------------------------
@pytest.mark.parametrize("value", [
    {"width": 0, "height": 100}, {"width": -300, "height": 100}, {"width": 300, "height": -1},
    {"width": 99999, "height": 100}, {"width": 300, "height": 99999},
    {"width": 300.5, "height": 100}, {"width": "300", "height": 100}, {"width": True, "height": 100},
    {"width": 300}, {"height": 100}, {"width": 300, "height": 100, "x": 1},
    [300, 100], "300x100", 5,
])
def test_validate_expandable_rejects(value):
    with pytest.raises(ValueError):
        store.validate_expandable(value)


def test_validate_expandable_accepts_bounds():
    assert store.validate_expandable(None) is None
    assert store.validate_expandable({"width": 80, "height": 40}) == {"width": 80, "height": 40}
    assert store.validate_expandable({"width": 1600, "height": 1200}) == {"width": 1600, "height": 1200}


def test_generator_clamps_oversized_sizes_but_rejects_bad_shapes():
    spec = load("clock-agenda")
    spec["expandable"] = {"width": 99999, "height": -5}
    assert generator.validate(copy.deepcopy(spec))["expandable"] == {"width": 1600, "height": 40}
    spec["expandable"] = {"width": 300}
    with pytest.raises(SpecError):
        generator.validate(spec)


def test_expanded_state_is_never_trusted_without_expandable():
    assert store.is_expanded({"expanded": True}) is False
    assert store.is_expanded({"expanded": "yes", "expandable": SIZE}) is False
    assert store.is_expanded({"expanded": True, "expandable": SIZE}) is True


# --- renderer smoke test (needs GTK and a display; skipped otherwise) ---------------------
@pytest.mark.parametrize("name", EXPANDABLE_EXAMPLES)
def test_native_view_toggles(name):
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            pytest.skip("no display")
        from pickit.native.render import NativeView
    except (ValueError, ImportError):
        pytest.skip("GTK 3 unavailable")
    spec = generator.validate(load(name))
    view = NativeView()
    view.load_widget(spec["ui"], spec["commands"], run_commands=False)
    revealer = view._expander["revealer"]
    assert revealer.get_reveal_child() is False
    view.set_expanded(True, animate=False)
    assert revealer.get_reveal_child() is True
    view.set_expanded(False, animate=False)
    assert revealer.get_reveal_child() is False
    # the state survives a rebuild (restored without animation)
    view.set_expanded(True, animate=False)
    view.update_ui(spec["ui"])
    assert view._expander["revealer"].get_reveal_child() is True
    view.shutdown()
