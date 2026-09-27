"""Widget files (.pickit): export, import and what an import must reject."""

import json
import subprocess
import sys

import pytest

from pickit import share

UI = {"type": "label", "text": "{cpu}%"}
SPEC = {"name": "CPU", "engine": "native", "width": 200, "height": 80, "position": "top-left",
        "commands": {"cpu": {"cmd": "echo 5", "interval": 2}}, "ui": UI}


@pytest.fixture
def widget(store):
    manifest = store.save_spec(SPEC, approved=True, prompt="a cpu label")
    manifest.update(x=10, y=20)
    store.save_manifest(manifest)
    return manifest


def test_roundtrip(widget, tmp_path):
    path = share.export_widget(widget["id"], tmp_path / "cpu.pickit")
    data = json.loads(path.read_text())
    assert data["pickit"] == share.FORMAT and data["exported_by"].startswith("Pickit ")
    # Nothing personal or trust-related leaves the machine.
    for key in ("id", "approved_hash", "history", "x", "y", "enabled"):
        assert key not in data
    assert share.read_widget_file(path) == SPEC


def test_html_roundtrip(store, tmp_path):
    spec = {**{k: v for k, v in SPEC.items() if k != "ui"}, "engine": "html", "html": "<p>hi</p>"}
    manifest = store.save_spec(spec)
    assert share.read_widget_file(share.export_widget(manifest["id"], tmp_path / "w.pickit")) == spec


def write(tmp_path, content, name="w.pickit"):
    path = tmp_path / name
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def test_import_ignores_approval(tmp_path):
    spec = share.read_widget_file(write(tmp_path, {**SPEC, "pickit": 1, "approved_hash": "abc", "id": "x"}))
    assert "approved_hash" not in spec and "id" not in spec


def test_plain_spec_json_is_accepted(tmp_path):
    assert share.read_widget_file(write(tmp_path, SPEC, "w.json"))["name"] == "CPU"


@pytest.mark.parametrize("content, error", [
    ("not json", "invalid JSON"),
    ([1, 2], "isn't a Pickit widget"),
    ({"hello": "world"}, "isn't a Pickit widget"),
    ({**SPEC, "pickit": 99}, "newer version"),
    ({**SPEC, "pickit": 1, "ui": {"type": "label", "text": "x", "onclick": "rm -rf ~"}}, "unknown property"),
    ({**SPEC, "pickit": 1, "ui": {"type": "label", "color": "red; background: url(evil)"}}, "isn't a valid"),
    ({**SPEC, "pickit": 1, "commands": {"x": {"cmd": ""}}}, "non-empty"),
])
def test_rejects(tmp_path, content, error):
    with pytest.raises(share.WidgetFileError, match=error):
        share.read_widget_file(write(tmp_path, content))


def test_rejects_huge_files(tmp_path):
    path = tmp_path / "big.pickit"
    path.write_bytes(b" " * (share.MAX_BYTES + 1))
    with pytest.raises(share.WidgetFileError, match="too large"):
        share.read_widget_file(path)


def test_missing_file(tmp_path):
    with pytest.raises(share.WidgetFileError, match="Could not read"):
        share.read_widget_file(tmp_path / "nope.pickit")


def test_default_filename():
    assert share.default_filename("World Clock!") == "world-clock.pickit"
    assert share.default_filename("⏰") == "widget.pickit"


def test_cli_export(widget, tmp_path):
    out = tmp_path / "exported.pickit"
    result = subprocess.run([sys.executable, "-m", "pickit", "export", widget["id"], str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert share.read_widget_file(out)["name"] == "CPU"
    missing = subprocess.run([sys.executable, "-m", "pickit", "export", "no-such-widget"],
                             capture_output=True, text=True)
    assert missing.returncode == 1 and "pickit list" in missing.stderr


def test_free_anchor(store):
    assert store.free_anchor("top-right") == "top-right"
    store.save_spec({**SPEC, "position": "top-right"})
    assert store.free_anchor("top-right") == "top-left"
    moved = store.save_spec({**SPEC, "position": "top-left"})
    moved.update(x=5, y=5)  # moved widgets no longer sit on their anchor
    store.save_manifest(moved)
    assert store.free_anchor("top-right") == "top-left"
    hidden = store.save_spec({**SPEC, "position": "top-left"})
    hidden["enabled"] = False
    store.save_manifest(hidden)
    assert store.free_anchor("top-right") == "top-left"
