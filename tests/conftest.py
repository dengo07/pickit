import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """pickit.store pointed at a temporary XDG data directory."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from pickit import runtime
    from pickit import store as store_module
    importlib.reload(runtime)
    return importlib.reload(store_module)
