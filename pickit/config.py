"""User configuration stored at ~/.config/pickit/config.json."""

import json
import os

from . import runtime

CONFIG_DIR = runtime.CONFIG_HOME / "pickit"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    # "claude-cli" uses the installed `claude` binary; "anthropic" uses the Python SDK.
    # "auto" picks the CLI when it's installed, else the API.
    "backend": "auto",
    # Empty means "whatever the Claude CLI defaults to". Accepts aliases like "sonnet".
    "cli_model": "",
    "api_model": "claude-opus-5",
    # Optional; if empty the SDK falls back to ANTHROPIC_API_KEY / `ant auth login`.
    "anthropic_api_key": "",
    # Start the desktop daemon at login so widgets survive reboots.
    "autostart": True,
    # Default engine in the maker: "auto" (native whenever possible), "native" or "html".
    "engine": "auto",
    "developer_extras": False,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    os.chmod(CONFIG_FILE, 0o600)  # may contain an API key
