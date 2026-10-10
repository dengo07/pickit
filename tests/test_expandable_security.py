"""Hostile input around expandable widgets: imported files, hand-edited sizes, infinity."""

import json

import pytest

from pickit import bridge, placement, share

HTML = {"name": "Evil", "engine": "html", "width": 300, "height": 90, "html": "<html></html>",
        "expandable": {"width": 300, "height": 320}}


def test_import_never_carries_expanded_state(store):
    spec = share.parse_widget_data({**HTML, "pickit": 1, "expanded": True})
    assert "expanded" not in spec
    manifest = store.save_spec(spec)
    assert "expanded" not in manifest and not store.is_expanded(manifest)


def test_import_clamps_or_rejects_hostile_expandable():
    big = share.parse_widget_data({**HTML, "expandable": {"width": 10**9, "height": 10**9}})
    assert big["expandable"] == {"width": 1600, "height": 1200}
    for bad in ({"width": 1e999, "height": 300}, {"width": 300, "height": -1e999},
                {"width": [1], "height": 300}, {"width": 300, "height": None}, 7, ["a"],
                {"width": 300, "height": 300, "extra": "<script>"}):
        with pytest.raises(share.WidgetFileError):
            share.parse_widget_data({**HTML, "expandable": bad})


def test_infinite_width_is_a_spec_error_not_a_crash(tmp_path):
    path = tmp_path / "evil.pickit"
    path.write_text(json.dumps(HTML).replace('"width": 300,', '"width": 1e999,', 1))
    with pytest.raises(share.WidgetFileError):
        share.read_widget_file(path)


def test_expander_in_html_or_without_declaration_is_rejected():
    native = {"name": "N", "engine": "native", "width": 200, "height": 80,
              "ui": {"type": "expander", "header": [{"type": "text", "text": "x"}], "children": []}}
    with pytest.raises(share.WidgetFileError):
        share.parse_widget_data(native)  # an expander needs `expandable`


@pytest.mark.parametrize("w,h", [(float("inf"), 300), (300, float("-inf")), (float("nan"), 300),
                                 ("300", 300), (None, 300), ([1], 300), ({}, 300), (True, 300)])
def test_safe_size_falls_back_on_garbage(w, h):
    assert placement.safe_size(w, h, (1920, 1080), (320, 200)) == (320, 200)


def test_safe_size_clamps_numbers():
    assert placement.safe_size(10**12, 10**12, None, (1, 1)) == (1600, 1200)
    assert placement.safe_size(1, 1, None, (320, 200)) == (80, 40)
    assert placement.safe_size(1000, 900, (800, 600), (1, 1)) == (800 - 2 * placement.MARGIN,
                                                                 600 - 2 * placement.MARGIN)


@pytest.mark.parametrize("bad", ["yes", 1, [1], True, None])
def test_hand_edited_expandable_is_not_expanded(bad):
    from pickit import store
    assert not store.is_expanded({"expanded": True, "expandable": bad})


def test_only_a_real_true_with_a_real_block_is_expanded():
    from pickit import store
    assert not store.is_expanded({"expanded": "true", "expandable": {"width": 300, "height": 300}})
    assert not store.is_expanded({"expanded": 1, "expandable": {"width": 300, "height": 300}})
    assert store.is_expanded({"expanded": True, "expandable": {"width": 300, "height": 300}})


def test_messages_from_a_page_can_only_pick_one_of_three_words():
    for action in ("__import__('os')", "expand ", "Toggle", 1, True, {"a": 1}, b"expand"):
        assert bridge.parse_expand_message({"type": "expand", "action": action}) is None


def test_flood_is_limited_to_one_request_per_interval():
    lim = bridge.ExpandLimiter(220)
    accepted = sum(lim.allow(1000 + i) for i in range(200))  # 200 requests inside 200 ms
    assert accepted == 1


def test_html_view_formats_only_literal_booleans():
    pytest.importorskip("gi")
    try:
        import inspect

        from pickit import html_view
    except (ImportError, ValueError):
        pytest.skip("WebKit is not available")
    src = inspect.getsource(html_view.WidgetView._send_expanded)
    assert "'true' if self._expanded else 'false'" in src


def test_csp_and_sandbox_stay_strict():
    pytest.importorskip("gi")
    try:
        from pickit import html_view, sandbox
    except (ImportError, ValueError):
        pytest.skip("WebKit is not available")
    policy = html_view.CSP.split("; ")
    for directive in ("default-src 'none'", "connect-src 'none'", "form-action 'none'",
                      "frame-src 'none'", "worker-src 'none'", "base-uri 'none'", "img-src data: blob:"):
        assert directive in policy
    assert not any("http" in d for d in policy if d.split()[0] in ("default-src", "connect-src", "img-src"))
    assert sandbox.argv("echo hi", False, "restricted")[-2] == "0"
    assert sandbox.mode("nonsense") == sandbox.INVALID
