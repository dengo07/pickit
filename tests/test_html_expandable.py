"""HTML expandable widgets: the bridge messages, size limits and persisted state (no GTK window)."""

import pytest

from pickit import bridge, generator, placement

HTML_SPEC = {"name": "Agenda", "engine": "html", "width": 300, "height": 90, "position": "center",
             "expandable": {"width": 300, "height": 320}, "html": "<html></html>"}


def test_bridge_js_exposes_only_enum_requests():
    for word in ("expand", "collapse", "toggle"):
        assert f'action: "{word}"' in bridge.BRIDGE_JS
    assert "pickit-expand" in bridge.BRIDGE_JS and "pickitExpanded" in bridge.BRIDGE_JS
    assert "width" not in bridge.BRIDGE_JS.split("expand()")[1].split("theme:")[0]  # no size from the page


@pytest.mark.parametrize("action", ["expand", "collapse", "toggle"])
def test_parse_accepts_the_three_actions(action):
    assert bridge.parse_expand_message({"type": "expand", "action": action}) == action


@pytest.mark.parametrize("msg", [
    None, "expand", [], {}, {"type": "expand"}, {"type": "expand", "action": "resize"},
    {"type": "expand", "action": "EXPAND"}, {"type": "expand", "action": ["expand"]},
    {"type": "expand", "action": None}, {"type": "run", "action": "expand"},
])
def test_parse_drops_everything_else(msg):
    assert bridge.parse_expand_message(msg) is None


def test_parse_ignores_extra_fields():
    msg = {"type": "expand", "action": "toggle", "width": 5000, "height": 5000}
    assert bridge.parse_expand_message(msg) == "toggle"  # only the action word is ever read


def test_expand_target():
    assert bridge.expand_target("expand", True) is True
    assert bridge.expand_target("collapse", True) is False
    assert bridge.expand_target("toggle", True) is False
    assert bridge.expand_target("toggle", False) is True


def test_limiter_allows_one_request_per_interval():
    lim = bridge.ExpandLimiter(220)
    assert lim.allow(1000)
    assert not lim.allow(1100)
    assert not lim.allow(1219)
    assert lim.allow(1220)
    assert not lim.allow(1221)  # a dropped request doesn't extend the window, an accepted one restarts it


def test_clamp_size():
    assert placement.clamp_size(320, 360) == (320, 360)
    assert placement.clamp_size(99999, 99999) == (1600, 1200)
    assert placement.clamp_size(-5, 0) == (80, 40)
    # the smaller of the declared size and the monitor's work area wins
    assert placement.clamp_size(1000, 900, (800, 600)) == (800 - 2 * placement.MARGIN, 600 - 2 * placement.MARGIN)
    assert placement.clamp_size(300, 200, (1920, 1080)) == (300, 200)
    assert placement.clamp_size(300, 200, (10, 10)) == (80, 40)  # never below the minimum


@pytest.mark.parametrize("bad", [
    {"width": 300}, {"height": 300}, {"width": 300, "height": 300, "x": 1},
    {"width": "300", "height": 300}, {"width": 300.0, "height": 300}, {"width": True, "height": 300},
    {"width": 79, "height": 300}, {"width": 300, "height": 39}, {"width": 1601, "height": 300},
    {"width": 300, "height": 1201}, {"width": -300, "height": 300}, "big", 5, [], [300, 300],
])
def test_validate_expandable_rejects_hostile_values(store, bad):
    with pytest.raises(ValueError):
        store.validate_expandable(bad)


def test_validate_expandable_accepts_bounds(store):
    assert store.validate_expandable(None) is None
    assert store.validate_expandable({"width": 80, "height": 40}) == {"width": 80, "height": 40}
    assert store.validate_expandable({"width": 1600, "height": 1200}) == {"width": 1600, "height": 1200}


def test_generator_clamps_and_rejects_shape_errors():
    out = generator.validate({**HTML_SPEC, "expandable": {"width": 99999, "height": 5}})
    assert out["expandable"] == {"width": 1600, "height": 40}
    assert "expandable" not in generator.validate({k: v for k, v in HTML_SPEC.items() if k != "expandable"})
    for bad in ({"width": 300}, {"width": "wide", "height": 300}, "big", {"width": 1, "height": 1, "x": 1}):
        with pytest.raises(generator.SpecError):
            generator.validate({**HTML_SPEC, "expandable": bad})


def test_expanded_is_live_state_not_spec(store):
    assert "expanded" in store.LIVE_FIELDS
    manifest = store.save_spec(HTML_SPEC)
    before = store.signature(manifest)
    assert store.signature({**manifest, "expanded": True}) == before  # toggling never reloads
    manifest["expanded"] = True
    assert "expanded" not in store.to_spec(manifest)
    assert store.to_spec(manifest)["expandable"] == HTML_SPEC["expandable"]


@pytest.mark.parametrize("value", [1, "true", "yes", [True], {}, None, 0])
def test_non_bool_expanded_loads_collapsed(store, value):
    manifest = store.save_spec(HTML_SPEC)
    assert not store.is_expanded({**manifest, "expanded": value})


def test_stale_expanded_without_expandable_is_ignored(store):
    manifest = store.save_spec({k: v for k, v in HTML_SPEC.items() if k != "expandable"})
    assert not store.is_expanded({**manifest, "expanded": True})
    assert store.is_expanded({**store.save_spec(HTML_SPEC), "expanded": True})


def test_refine_without_expandable_clears_the_state(store):
    manifest = store.save_spec(HTML_SPEC)
    manifest["expanded"] = True
    store.save_manifest(manifest)
    plain = store.save_spec({k: v for k, v in HTML_SPEC.items() if k != "expandable"}, manifest["id"])
    assert "expandable" not in plain and "expanded" not in plain


def test_save_spec_refuses_a_bad_block(store):
    with pytest.raises(ValueError):
        store.save_spec({**HTML_SPEC, "expandable": {"width": 99999, "height": 300}})


def test_expandable_does_not_change_approvals(store):
    spec = {**HTML_SPEC, "commands": {"c": {"cmd": "date", "interval": 5}}}
    manifest = store.save_spec(spec, approved=True)
    other = {**manifest, "expandable": {"width": 500, "height": 500}}
    assert store.is_approved(other)  # it can't run anything, so it can't change what is approved
    assert store.commands_hash(other["commands"]) == store.commands_hash(manifest["commands"])
