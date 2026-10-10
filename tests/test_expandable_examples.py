"""The shipped expandable examples (two native, one HTML fixture) pass the same validation as generated specs."""

import json
from pathlib import Path

import pytest

from pickit import generator

ROOT = Path(__file__).resolve().parent
NATIVE = ROOT.parent / "pickit" / "prompts" / "native_examples"
HTML_FIXTURE = ROOT / "fixtures" / "expandable-html.json"


def _load(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("name", ["clock-agenda", "system-details"])
def test_native_examples_validate(name):
    out = generator.validate(_load(NATIVE / f"{name}.json"))
    assert out["engine"] == "native"
    assert out["expandable"]["height"] > out["height"]


def test_html_fixture_validates_and_uses_only_enum_calls():
    spec = _load(HTML_FIXTURE)
    out = generator.validate(spec)
    assert out["engine"] == "html" and out["expandable"] == {"width": 300, "height": 260}
    html = spec["html"]
    for call in ("widget.toggle()", "widget.collapse()"):
        assert call in html
    assert "http://" not in html and "https://" not in html  # CSP blocks the network anyway


def test_html_fixture_saves_collapsed(store):
    manifest = store.save_spec(_load(HTML_FIXTURE))
    assert not store.is_expanded(manifest)
    assert store.to_spec(manifest)["expandable"] == {"width": 300, "height": 260}
