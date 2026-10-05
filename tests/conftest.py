import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """pickit.store pointed at a temporary XDG data directory."""
    monkeypatch.setenv("PICKIT_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("PICKIT_CONFIG_HOME", str(tmp_path / "config"))
    from pickit import config, runtime, sandbox
    from pickit import store as store_module
    importlib.reload(runtime)
    importlib.reload(config)    # its folder too, so nothing reads your real settings
    sandbox._cache = None
    return importlib.reload(store_module)
