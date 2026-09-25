"""User configuration stored at ~/.config/pickit/config.json."""

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
