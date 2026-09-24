import json
import re
from pathlib import Path

import pytest

from pickit import generator
from pickit.native.spec import UISpecError, validate_ui

EXAMPLES = sorted((Path(__file__).parent.parent / "pickit" / "prompts" / "native_examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_shipped_examples_are_valid(path):
    spec = json.loads(path.read_text())
    assert generator.validate(spec)["engine"] == "native"


def test_examples_exist():
    assert {p.stem for p in EXAMPLES} >= {"battery", "clock", "now-playing", "system-meters", "weather"}


@pytest.mark.parametrize("tree, message", [
    ({"type": "label", "colour": "red"}, 'unknown property "colour"'),
    ({"type": "blink"}, 'unknown component "blink"'),
    ({"type": "label", "color": "red; background: url(x)"}, "not a color"),
    ({"type": "card", "background": "url(file:///etc/passwd)"}, "not a color"),
    ({"type": "button", "text": "Go", "action": "nope"}, "not a declared command"),
    ({"type": "button", "text": "Go", "action": "poll"}, "interval"),
    ({"type": "ring"}, '"value" is required'),
    ({"type": "label", "visible": "{a} == ("}, "expected a value in condition"),
    ({"type": "column", "children": [{"type": "label", "size": "big"}]}, "children[0].size"),
])
def test_invalid_trees_are_rejected_with_a_path(tree, message):
    with pytest.raises(UISpecError, match=re.escape(message)):
        validate_ui(tree, {"poll": {"cmd": "date", "interval": 5}})


def test_choice_values_are_checked_too():
    ok = {"type": "label", "color": [{"when": "{a} > 1", "value": "#fff"}, "#000"]}
    assert validate_ui(ok)
    with pytest.raises(UISpecError):
        validate_ui({"type": "label", "color": [{"when": "{a} > 1", "value": "red;"}, "#000"]})


def test_engine_can_be_forced():
    spec = json.loads(EXAMPLES[0].read_text())
    with pytest.raises(generator.SpecError, match="html engine"):
        generator.validate(spec, "html")
    assert generator.validate(spec, "native")["ui"]
