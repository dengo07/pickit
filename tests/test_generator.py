import json

import pytest

from pickit import generator
from pickit.generator import SpecError

HTML = "<!doctype html><html><body>hi</body></html>"


def spec(**overrides):
    base = {"name": "Clock", "width": 300, "height": 120, "position": "top-left", "commands": {}, "html": HTML}
    base.update(overrides)
    return base


class TestExtractJson:
    def test_plain_object(self):
        assert generator._extract_json(json.dumps(spec()))["name"] == "Clock"

    def test_code_fence_and_prose(self):
        text = "Here you go:\n```json\n" + json.dumps(spec()) + "\n```\nEnjoy!"
        assert generator._extract_json(text)["width"] == 300

    def test_no_object(self):
        with pytest.raises(SpecError):
            generator._extract_json("sorry, no widget today")

    def test_invalid_json(self):
        with pytest.raises(SpecError):
            generator._extract_json('{"name": "x", }')


class TestValidate:
    def test_keeps_valid_spec(self):
        assert generator.validate(spec()) == spec()

    def test_clamps_size(self):
        out = generator.validate(spec(width=5, height=99999))
        assert (out["width"], out["height"]) == (80, 1200)

    def test_unknown_position_falls_back(self):
        assert generator.validate(spec(position="upside-down"))["position"] == "top-right"

    def test_requires_html(self):
        with pytest.raises(SpecError):
            generator.validate(spec(html=""))

    def test_command_shorthand_and_min_interval(self):
        out = generator.validate(spec(commands={"a": "uptime", "b": {"cmd": "date", "interval": 0.2}}))
        assert out["commands"] == {"a": {"cmd": "uptime", "interval": 0}, "b": {"cmd": "date", "interval": 1}}

    def test_rejects_empty_command(self):
        with pytest.raises(SpecError):
            generator.validate(spec(commands={"a": {"cmd": "  "}}))


class FakeBackend:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_generate_repairs_bad_output_once():
    backend = FakeBackend("not json", json.dumps(spec(name="Fixed")))
    assert generator.generate(backend, "a clock")["name"] == "Fixed"
    assert len(backend.calls) == 2
    assert "not usable" in backend.calls[1][-1]["content"]


def test_generate_sends_current_widget_when_refining():
    backend = FakeBackend(json.dumps(spec(name="Blue")))
    generator.generate(backend, "make it blue", current=spec())
    prompt = backend.calls[0][0]["content"]
    assert "CURRENT WIDGET JSON" in prompt and "make it blue" in prompt
