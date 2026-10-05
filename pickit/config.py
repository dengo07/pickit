"""User configuration stored at ~/.config/pickit/config.json; API keys go to the desktop
keyring when there is one (see secret_store.py)."""

import json
import os

from . import runtime

CONFIG_DIR = runtime.CONFIG_HOME / "pickit"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    # "claude-cli" (the `claude` binary), "anthropic" (Python SDK), "ollama", "openrouter", or
    # "auto": the first that's set up, in that order.
    "backend": "auto",
    # Empty means "whatever the Claude CLI defaults to". Accepts aliases like "sonnet".
    "cli_model": "",
    "api_model": "claude-opus-5",
    # Optional; if empty the SDK falls back to ANTHROPIC_API_KEY / `ant auth login`.
    "anthropic_api_key": "",
    # Ollama: a local model server. An empty model means the largest installed one.
    "ollama_url": "",  # empty: $OLLAMA_HOST, else http://localhost:11434
    "ollama_model": "",
    "ollama_context": 16384,  # minimum context window in tokens; Pickit's instructions alone are ~8k
    # OpenRouter: any hosted model through one key (falls back to OPENROUTER_API_KEY).
    "openrouter_api_key": "",
    "openrouter_model": "anthropic/claude-sonnet-5",
    # Start the desktop daemon at login so widgets survive reboots.
    "autostart": True,
    # The command the login entry runs instead of Pickit's own, for example to keep Pickit in a
    # Firejail or bubblewrap sandbox: "firejail --profile=pickit ~/Apps/Pickit.AppImage run".
    "autostart_command": "",
    # Default engine in the maker: "auto" (native whenever possible), "native" or "html".
    "engine": "auto",
    "developer_extras": False,
    "lock_widgets": False,  # no widget can be dragged (each one can also be locked on its own)
    # How approved widget commands run (sandbox.py): "host" (full access), "restricted" (a
    # bubblewrap sandbox) or your own wrapper, e.g. ["firejail", "--profile=pickit-widget", "--"].
    "command_runner": "host",
}


# Kept in the keyring, not in config.json, whenever a keyring is available.
SECRET_KEYS = ("anthropic_api_key", "openrouter_api_key")
_from_keyring: dict[str, str] = {}  # what this process read from (or wrote to) the keyring


def load(with_secrets: bool = False) -> dict:
    """The settings. `with_secrets` also reads the API keys from the keyring; only the Pickit
    window needs them, so the widget daemon never touches the keyring (or asks to unlock it)."""
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if with_secrets:
        from . import secret_store
        still_in_file = any(cfg.get(key) for key in SECRET_KEYS)
        for key in SECRET_KEYS:
            if not cfg.get(key):
                cfg[key] = _from_keyring[key] = secret_store.get(key) or ""
        if still_in_file:
            save(cfg)  # keys saved before the keyring was used: move them there
    return cfg


def save(cfg: dict) -> None:
    from . import secret_store
    data = dict(cfg)
    for key in SECRET_KEYS:
        value = data.get(key) or ""
        if value and secret_store.set(key, value):
            data[key] = ""
            _from_keyring[key] = value
        elif not value and _from_keyring.get(key):
            secret_store.clear(key)  # removed in Settings
            _from_keyring[key] = ""
        # Otherwise (no keyring) the key stays in the file, readable only by you.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    os.chmod(CONFIG_FILE, 0o600)  # may contain an API key when there's no keyring
