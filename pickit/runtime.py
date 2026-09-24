"""Where are we running (source checkout, Flatpak or AppImage) and how to reach the host."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

APP_ID = "io.github.dengo07.Pickit"
IN_FLATPAK = os.path.exists("/.flatpak-info")
APPIMAGE = os.environ.get("APPIMAGE")  # set by the AppImage runtime to the .AppImage path
PROJECT_DIR = Path(__file__).resolve().parent.parent

# Inside Flatpak the XDG_* variables point into the sandbox (~/.var/app/...). Use the real
# directories instead (the manifest grants access), so the source, Flatpak and AppImage
# versions all share the same widgets, settings and autostart entry.
if IN_FLATPAK:
    CONFIG_HOME = Path.home() / ".config"
    DATA_HOME = Path.home() / ".local" / "share"
else:
    CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def host_argv(argv: list[str]) -> list[str]:
    """Wrap a command so it runs on the host system (escapes the Flatpak sandbox)."""
    if IN_FLATPAK:
        return ["flatpak-spawn", "--host", *argv]
    return argv


def host_env() -> dict:
    """Environment for host commands: drop variables that point into our bundle."""
    env = dict(os.environ)
    if APPIMAGE:
        for key in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "GI_TYPELIB_PATH", "GDK_PIXBUF_MODULE_FILE",
                    "GIO_MODULE_DIR", "GTK_PATH", "GTK_EXE_PREFIX", "GTK_DATA_PREFIX", "GSETTINGS_SCHEMA_DIR",
                    "WEBKIT_INJECTED_BUNDLE_PATH", "GST_PLUGIN_SYSTEM_PATH_1_0", "GST_PLUGIN_PATH_1_0",
                    "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE", "XDG_DATA_DIRS_ORIG"):
            env.pop(key, None)
        if "XDG_DATA_DIRS_ORIG" in os.environ:
            env["XDG_DATA_DIRS"] = os.environ["XDG_DATA_DIRS_ORIG"]
    return env


def self_command(*args: str) -> list[str]:
    """Command line (as run on the host) that starts this app with `args`."""
    if IN_FLATPAK:
        return ["flatpak", "run", "--command=pickit", APP_ID, *args]
    if APPIMAGE:
        return [APPIMAGE, *args]
    return ["env", f"PYTHONPATH={PROJECT_DIR}", sys.executable, "-m", "pickit", *args]


def spawn_self(*args: str, log_path: Path | None = None) -> None:
    """Start another instance of this app fully detached (survives this process exiting).

    Inside Flatpak the new process is started through the host, so it gets its own
    sandbox instead of being killed when this sandbox's main process exits.
    """
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    subprocess.Popen(host_argv(self_command(*args)), env=host_env(), cwd=str(Path.home()),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def autostart_exec() -> str:
    return shlex.join(self_command("run"))


_CLAUDE_PROBE = r'''
for p in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" "$HOME/.npm-global/bin/claude" \
         "/usr/local/bin/claude" "/usr/bin/claude"; do
  [ -x "$p" ] && { echo "$p"; exit 0; }
done
command -v claude 2>/dev/null && exit 0
# nvm / custom PATHs are usually only set up by interactive shells
bash -lic 'command -v claude' 2>/dev/null | tail -n1
'''

_claude_path: str | None = None


def find_claude() -> str | None:
    """Locate the Claude Code CLI on the host, even when PATH (e.g. from a menu launch) lacks it."""
    global _claude_path
    if _claude_path:
        return _claude_path
    try:
        out = subprocess.run(host_argv(["sh", "-c", _CLAUDE_PROBE]), capture_output=True, text=True,
                             timeout=10, env=host_env(), stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip().startswith("/")]
    _claude_path = lines[-1] if lines else None
    return _claude_path
