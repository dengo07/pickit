"""Settings: API keys in the keyring (with config.json as the fallback), and the login entry."""

import importlib
import json

import pytest


@pytest.fixture
def cfg_env(tmp_path, monkeypatch):
    """config, secret_store and autostart pointed at a temporary folder, with a fake keyring."""
    monkeypatch.setenv("PICKIT_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PICKIT_DATA_HOME", str(tmp_path / "data"))
    from pickit import autostart, config, runtime, secret_store
    importlib.reload(runtime)
    config = importlib.reload(config)
    autostart = importlib.reload(autostart)
    keyring = {"works": True, "items": {}}

    def store(name, value):
        if keyring["works"]:
            keyring["items"][name] = value
        return keyring["works"]
    monkeypatch.setattr(secret_store, "get", lambda name: keyring["items"].get(name))
    monkeypatch.setattr(secret_store, "set", store)
    monkeypatch.setattr(secret_store, "clear", lambda name: keyring["items"].pop(name, None))
    return config, autostart, keyring


def in_file(config):
    return json.loads(config.CONFIG_FILE.read_text())


def test_keys_go_to_the_keyring(cfg_env):
    config, _, keyring = cfg_env
    cfg = config.load(with_secrets=True)
    cfg["openrouter_api_key"] = "sk-or-secret"
    config.save(cfg)
    assert in_file(config)["openrouter_api_key"] == ""
    assert keyring["items"]["openrouter_api_key"] == "sk-or-secret"
    assert config.load(with_secrets=True)["openrouter_api_key"] == "sk-or-secret"


def test_the_daemon_never_reads_the_keyring(cfg_env):
    config, _, keyring = cfg_env
    keyring["items"]["anthropic_api_key"] = "sk-ant-secret"
    assert config.load()["anthropic_api_key"] == ""


def test_keys_from_older_versions_move_to_the_keyring(cfg_env):
    config, _, keyring = cfg_env
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_FILE.write_text(json.dumps({"anthropic_api_key": "sk-ant-old"}))
    assert config.load(with_secrets=True)["anthropic_api_key"] == "sk-ant-old"
    assert keyring["items"]["anthropic_api_key"] == "sk-ant-old"
    assert in_file(config)["anthropic_api_key"] == ""


def test_without_a_keyring_keys_stay_in_the_file(cfg_env):
    config, _, keyring = cfg_env
    keyring["works"] = False
    cfg = config.load(with_secrets=True)
    cfg["anthropic_api_key"] = "sk-ant-secret"
    config.save(cfg)
    assert in_file(config)["anthropic_api_key"] == "sk-ant-secret"
    assert config.CONFIG_FILE.stat().st_mode & 0o777 == 0o600


def test_removing_a_key_removes_it_from_the_keyring(cfg_env):
    config, _, keyring = cfg_env
    keyring["items"]["openrouter_api_key"] = "sk-or-secret"
    cfg = config.load(with_secrets=True)
    cfg["openrouter_api_key"] = ""
    config.save(cfg)
    assert "openrouter_api_key" not in keyring["items"]


def test_an_unreadable_keyring_is_never_wiped(cfg_env):
    """If the keyring stayed locked, the key reads as empty; saving must not delete it."""
    config, _, keyring = cfg_env
    cfg = config.load(with_secrets=True)       # nothing readable yet
    keyring["items"]["anthropic_api_key"] = "sk-ant-secret"
    config.save(cfg)
    assert keyring["items"]["anthropic_api_key"] == "sk-ant-secret"


def test_keyring_entries_belong_to_their_config_folder(cfg_env):
    config, _, _ = cfg_env
    from pickit import secret_store
    assert secret_store._attributes("anthropic_api_key") == {"key": "anthropic_api_key",
                                                             "config": str(config.CONFIG_DIR)}


def test_custom_autostart_command(cfg_env):
    _, autostart, _ = cfg_env
    autostart.set_enabled(True, "firejail --profile=pickit /opt/Pickit.AppImage run\nHidden=true 100%")
    lines = autostart.AUTOSTART_FILE.read_text().splitlines()
    assert "Exec=firejail --profile=pickit /opt/Pickit.AppImage run Hidden=true 100%%" in lines
    assert "Hidden=true" not in lines, "a newline must not add keys to the desktop entry"
    autostart.set_enabled(True)
    assert "firejail" not in autostart.AUTOSTART_FILE.read_text()
    autostart.set_enabled(False)
    assert not autostart.AUTOSTART_FILE.exists()
