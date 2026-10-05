"""How approved widget commands run: with your full account (the default), in a restricted
bubblewrap sandbox, or through a wrapper you choose (config "command_runner").

- "host": `bash -c` as you, with your files, network and desktop session. Inside the Flatpak
  this means on the host, through flatpak-spawn.
- "restricted": inside bubblewrap. The system is read-only; your home folder, every other home,
  /run (session and system sockets, including Docker's), /tmp and removable drives are hidden;
  D-Bus, X11, Wayland and SSH-agent variables are removed. Only commands marked
  `"network": true` can use the network. Sharing the host's network would also share the X
  server's abstract socket, which a command could use to read keys or type into other windows,
  so with pasta (the passt package) installed they get a network namespace of their own.
- a list such as ["firejail", "--profile=pickit-widget", "--"]: put in front of `bash -c`.

Every mode fails closed: if the runner is missing or the setting is invalid, the command doesn't
run, and never falls back to running with full access.
"""

import shlex

from . import config

TIMEOUT = 20
HOST, RESTRICTED, CUSTOM, INVALID = "host", "restricted", "custom", "invalid"
FAILED = 126  # exit code when the runner refuses (missing or misconfigured); the command never ran

# Runs on the host (after flatpak-spawn in the Flatpak): sets up bubblewrap there.
# Arguments: <network 0|1> <command>.
_RESTRICTED = r'''
command -v bwrap >/dev/null 2>&1 || {
  echo "pickit: the restricted command runner needs bubblewrap (bwrap);" \
       "install it, or choose full access in Settings" >&2
  exit 126; }
net=$1; cmd=$2
state="${XDG_CACHE_HOME:-$HOME/.cache}/pickit/sandbox"
mkdir -p "$state/tmp" || exit 126
set -- --ro-bind / / --dev /dev --proc /proc \
  --tmpfs /home --tmpfs "$HOME" --tmpfs /run --bind "$state/tmp" /tmp
for d in /media /mnt /var/home /run/media; do [ -d "$d" ] && set -- "$@" --tmpfs "$d"; done
rc=$(readlink -f /etc/resolv.conf)
pasta=
if [ "$net" != 1 ]; then
  set -- "$@" --unshare-net
elif command -v pasta >/dev/null 2>&1; then
  # Its own network namespace, connected through pasta: internet, but not the X server's
  # abstract socket or other host-local services. DNS goes through pasta's forwarder.
  echo "nameserver 169.254.1.53" > "$state/resolv.conf" || exit 126
  set -- "$@" --ro-bind "$state/resolv.conf" "$rc"
  pasta=1
else
  # The host's network: name resolution lives in /run on most systems, so bring back just that.
  [ -d /run/systemd/resolve ] && set -- "$@" --ro-bind /run/systemd/resolve /run/systemd/resolve
  case "$rc" in /run/systemd/resolve/*) ;; /run/*) [ -f "$rc" ] && set -- "$@" --ro-bind "$rc" "$rc" ;; esac
fi
for v in DBUS_SESSION_BUS_ADDRESS DBUS_SYSTEM_BUS_ADDRESS DISPLAY WAYLAND_DISPLAY XAUTHORITY \
         SSH_AUTH_SOCK GPG_AGENT_INFO SESSION_MANAGER XDG_RUNTIME_DIR; do
  set -- "$@" --unsetenv "$v"
done
set -- bwrap "$@" --setenv HOME "$HOME" --chdir "$HOME" --unshare-pid --unshare-ipc --unshare-uts \
  --unshare-cgroup-try --die-with-parent --new-session -- bash -c "$cmd"
if [ -n "$pasta" ]; then
  exec pasta --config-net --quiet --dns-forward 169.254.1.53 -- "$@"
fi
exec "$@"
'''


def network_isolated() -> bool:
    """Whether commands that use the internet get their own network namespace (pasta, from
    the passt package, is installed on the host); otherwise they share the host's network."""
    import subprocess

    from . import runtime
    try:
        return subprocess.run(runtime.host_argv(["sh", "-c", "command -v pasta"]), capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# A custom runner: refuse to run if its program isn't there.
_CUSTOM = r'''
command -v "$1" >/dev/null 2>&1 || { echo "pickit: the command runner \"$1\" isn't installed" >&2; exit 126; }
exec "$@"
'''


def mode(runner) -> str:
    if runner in (None, "", HOST):
        return HOST
    if runner == RESTRICTED:
        return RESTRICTED
    if isinstance(runner, list) and runner and all(isinstance(a, str) and a for a in runner):
        return CUSTOM
    return INVALID


def argv(cmd: str, network: bool = False, runner=None) -> list[str]:
    """The command line (before flatpak-spawn) that runs `cmd` the way `runner` says."""
    limit = ["timeout", "-k", "2", str(TIMEOUT)]
    m = mode(runner)
    if m == HOST:
        return [*limit, "bash", "-c", cmd]
    if m == RESTRICTED:
        return [*limit, "sh", "-c", _RESTRICTED, "pickit-restricted", "1" if network else "0", cmd]
    if m == CUSTOM:
        return [*limit, "sh", "-c", _CUSTOM, "pickit-runner", *runner, "bash", "-c", cmd]
    refuse = 'echo "pickit: the command_runner setting is invalid; nothing runs until it\'s fixed" >&2'
    return ["sh", "-c", f"{refuse}; exit {FAILED}"]


_cache: tuple | None = None


def current():
    """The configured runner, re-read when config.json changes (Settings is another process)."""
    global _cache
    try:
        stamp = config.CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        stamp = None
    if _cache is None or _cache[0] != stamp:
        _cache = (stamp, config.load().get("command_runner", HOST))
    return _cache[1]


def describe(runner=None) -> tuple[str, str]:
    """(headline, details) for the approval dialog and Settings."""
    m = mode(runner)
    if m == HOST:
        return ("Runs with full access to your account",
                "Like pasting the command into your terminal: it can read and change your files, use the "
                "network and talk to your desktop session. Settings can run commands in a restricted sandbox.")
    if m == RESTRICTED:
        return ("Runs in a restricted sandbox",
                "It can read system information, but not your home folder, other programs' sockets or your "
                "desktop session. Only commands marked as using the internet can reach the network.")
    if m == CUSTOM:
        return ("Runs through your command runner", "Every command starts with: " + shlex.join(runner))
    return ("Commands can't run", "The command_runner setting in config.json is invalid, so Pickit runs nothing.")
