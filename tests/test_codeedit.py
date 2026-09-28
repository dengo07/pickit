"""Editing widgets as code: split/join with validation, error positions, component paths."""

import json

import pytest

from pickit import codeedit, generator
from pickit.codeedit import CodeError

UI = {"type": "card", "children": [
    {"type": "label", "text": "{now|time:%H:%M}", "size": 40},
    {"type": "row", "children": [{"type": "ring", "value": "{c.cpu}", "size": 90}]},
]}
NATIVE = {"name": "Clock", "engine": "native", "width": 300, "height": 150, "position": "top-left",
          "commands": {"c": {"cmd": "echo cpu=5", "interval": 2}}, "ui": UI}
HTML = {**{k: v for k, v in NATIVE.items() if k != "ui"}, "engine": "html", "html": "<p class='x'>hi</p>"}


@pytest.mark.parametrize("spec", [NATIVE, HTML], ids=["native", "html"])
def test_roundtrip(spec):
    settings, layout = codeedit.split_spec(spec)
    assert "engine" not in json.loads(settings)  # the engine isn't edited as code
    assert codeedit.join_spec(settings, layout, spec["engine"]) == generator.validate(spec)


def test_edits_are_applied():
    settings, layout = codeedit.split_spec(NATIVE)
    settings = settings.replace('"width": 300', '"width": 420')
    layout = layout.replace('"size": 40', '"size": 64')
    spec = codeedit.join_spec(settings, layout, "native")
    assert spec["width"] == 420 and spec["ui"]["children"][0]["size"] == 64


def test_engine_cannot_be_switched_from_settings():
    settings, layout = codeedit.split_spec(NATIVE)
    settings = settings.replace('"name"', '"engine": "html", "name"')
    assert codeedit.join_spec(settings, layout, "native")["engine"] == "native"


def test_json_syntax_error_points_at_it():
    settings, layout = codeedit.split_spec(NATIVE)
    broken = layout.replace('"size": 40', '"size": 40,,')
    with pytest.raises(CodeError) as e:
        codeedit.join_spec(settings, broken, "native")
    assert e.value.tab == "layout" and "line" in str(e.value)
    assert broken[e.value.span[0]] == ","


def test_validation_error_points_at_the_property():
    settings, layout = codeedit.split_spec(NATIVE)
    broken = layout.replace('"size": 90', '"sise": 90')
    with pytest.raises(CodeError, match='unknown property "sise"') as e:
        codeedit.join_spec(settings, broken, "native")
    assert broken[slice(*e.value.span)] == '"sise": 90'


def test_missing_required_property_points_at_the_component():
    settings, layout = codeedit.split_spec(NATIVE)
    broken = layout.replace('"value": "{c.cpu}", ', "").replace('"value": "{c.cpu}",', "")
    with pytest.raises(CodeError, match="required") as e:
        codeedit.join_spec(settings, broken, "native")
    assert broken[slice(*e.value.span)].lstrip().startswith("{") and '"ring"' in broken[slice(*e.value.span)]


def test_settings_errors():
    _, layout = codeedit.split_spec(NATIVE)
    with pytest.raises(CodeError, match="JSON object") as e:
        codeedit.join_spec("[]", layout, "native")
    assert e.value.tab == "settings"
    with pytest.raises(CodeError, match="Settings & commands") as e:
        codeedit.join_spec('{"commands": {"x": {"cmd": ""}}}', layout, "native")
    assert e.value.tab == "settings"


def test_json_spans_on_tricky_text():
    text = '{"a": [1, -2.5e3, "x\\"}", {"b": null}], "é": true}'
    spans = codeedit.json_spans(text)
    assert text[slice(*spans[("a", 2)])] == '"x\\"}"'
    assert text[slice(*spans[("a", 3, "b")])] == "null"
    assert text[slice(*spans[("é",)])] == "true"
    assert text[slice(*spans[()])] == text
    assert codeedit.json_spans("{not json") == {}


def test_paths_and_descriptions():
    ring = UI["children"][1]["children"][0]
    path = codeedit.node_path(UI, ring)
    assert path == ("children", 1, "children", 0)
    assert codeedit.node_at(UI, path) is ring
    assert codeedit.path_label(path) == "ui.children[1].children[0]"
    assert codeedit.node_path(UI, {"type": "ring"}) is None  # by identity, not equality
    assert codeedit.error_path('ui.children[1].children[0] (ring): unknown property "x"') == path
    assert codeedit.error_path("ui (card): …") == ()
    assert codeedit.describe(UI["children"][0]) == "label “{now|time:%H:%M}”"
    assert codeedit.describe(UI) == "card"


@pytest.mark.parametrize("outer, expected", [
    ('<div class="card" style="x">', "<div class='card' style='x'>"),
    ('<h1 class="title big">Hello</h1>', "<h1 class='title big'>"),
    ('<p id="sub">w</p>', "<p id=sub>"),
    ("<body>", "<body>"),
])
def test_find_element(outer, expected):
    page = "<body><div class='card' style='x'><h1 class='title big'>Hello</h1><p id=sub>w</p></div></body>"
    span = codeedit.find_element(page, outer)
    assert page[slice(*span)] == expected


class Recorder:
    def __init__(self, reply):
        self.reply, self.messages = reply, None

    def complete(self, system, messages):
        self.messages = messages
        return json.dumps(self.reply)


def test_selected_part_reaches_the_model():
    backend = Recorder(NATIVE)
    ring = UI["children"][1]["children"][0]
    generator.generate(backend, "make this orange", NATIVE, "auto",
                       focus={"kind": "native", "path": "ui.children[1].children[0]", "node": ring})
    text = backend.messages[0]["content"]
    assert "SELECTED PART" in text and "ui.children[1].children[0]" in text and '"value": "{c.cpu}"' in text
    assert text.index("SELECTED PART") < text.index("Change request: make this orange")

    backend = Recorder(HTML)
    generator.generate(backend, "bigger", HTML, "auto",
                       focus={"kind": "html", "selector": "body > p.x", "html": "<p class=\"x\">hi</p>"})
    assert "the element `body > p.x`" in backend.messages[0]["content"]


def test_no_selection_no_section():
    backend = Recorder(NATIVE)
    generator.generate(backend, "bigger", NATIVE)
    assert "SELECTED PART" not in backend.messages[0]["content"]


def test_editable_properties():
    ring = UI["children"][1]["children"][0]
    props = {p["key"]: p for p in codeedit.editable_properties(ring)}
    assert props["value"]["set"] and props["value"]["value"] == "{c.cpu}"
    assert not props["thickness"]["set"] and props["thickness"]["value"] is None
    assert "children" not in props and "halign" in props      # common properties, no children
    assert props["halign"]["choices"] == ["center", "end", "fill", "start"]
    keys = list(props)
    assert keys.index("value") < keys.index("margin")           # its own properties first


def test_set_and_remove_property():
    path = ("children", 1, "children", 0)
    changed = codeedit.set_property(NATIVE, path, "thickness", 12)
    assert codeedit.node_at(changed["ui"], path)["thickness"] == 12
    assert "thickness" not in codeedit.node_at(NATIVE["ui"], path)     # the original is untouched
    back = codeedit.remove_property(changed, path, "thickness")
    assert "thickness" not in codeedit.node_at(back["ui"], path)
    themed = codeedit.set_property(NATIVE, path, "color", "{theme.accent}")
    assert codeedit.node_at(themed["ui"], path)["color"] == "{theme.accent}"


@pytest.mark.parametrize("key, value, error", [
    ("size", "huge", "whole number"),
    ("color", "red; background: url(x)", "not a color"),
    ("halign", "sideways", "must be one of"),
])
def test_invalid_edits_are_rejected(key, value, error):
    with pytest.raises(CodeError, match=error):
        codeedit.set_property(NATIVE, ("children", 1, "children", 0), key, value)


def test_required_properties_cannot_be_removed():
    with pytest.raises(CodeError, match="required"):
        codeedit.remove_property(NATIVE, ("children", 1, "children", 0), "value")
