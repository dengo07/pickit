"""Background daemon launching and start-at-login support (XDG autostart)."""

from pathlib import Path

from . import runtime

AUTOSTART_FILE = runtime.CONFIG_HOME / "autostart" / "pickit.desktop"


def spawn(*args: str) -> None:
    """Start `pickit <args>` fully detached from this process."""
    from .store import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    runtime.spawn_self(*args, log_path=DATA_DIR / "daemon.log")


def ensure_daemon() -> None:
    """Make sure the desktop daemon is running. A no-op if it already is (it's a unique app)."""
    spawn("run")


def is_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def set_enabled(enabled: bool) -> None:
    if not enabled:
        AUTOSTART_FILE.unlink(missing_ok=True)
        return
    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_FILE.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Pickit (desktop widgets)\n"
        "Comment=Keeps your AI-generated widgets on the desktop\n"
        f"Exec={runtime.autostart_exec()}\n"
        f"Icon={runtime.APP_ID}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=3\n"
        "NoDisplay=true\n"
    )


DATA_FILES = Path(__file__).resolve().parent / "data"


def install_launcher() -> None:
    """For the AppImage: add Pickit to the application menu on first run.

    (The Flatpak gets this from the system; a source checkout uses install.sh.)
    """
    if not runtime.APPIMAGE:
        return
    share = runtime.DATA_HOME
    icon = share / "icons" / "hicolor" / "scalable" / "apps" / f"{runtime.APP_ID}.svg"
    entry = share / "applications" / f"{runtime.APP_ID}.desktop"
    icon.parent.mkdir(parents=True, exist_ok=True)
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes((DATA_FILES / f"{runtime.APP_ID}.svg").read_bytes())
    desktop = (DATA_FILES / f"{runtime.APP_ID}.desktop").read_text()
    desktop = desktop.replace("Exec=pickit", f"Exec={runtime.shlex.quote(runtime.APPIMAGE)}")
    desktop += "TryExec=" + runtime.APPIMAGE + "\n"
    if not entry.exists() or entry.read_text() != desktop:
        entry.write_text(desktop)
