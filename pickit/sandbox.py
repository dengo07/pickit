"""How approved widget commands run: with your full account (the default), in a restricted
bubblewrap sandbox, or through a wrapper you choose (config "command_runner").

- "host": `bash -c` as you, with your files, network and desktop session. Inside the Flatpak
  this means on the host, through flatpak-spawn.
- "restricted": inside bubblewrap. The system is read-only; your home folder, every other home,
  /run (session and system sockets, including Docker's), /tmp and removable drives are hidden;
  the command starts with a short fixed list of environment variables (PATH, HOME, locale,
  time zone), so no API key, token, D-Bus, X11, Wayland or SSH-agent variable reaches it. Only commands marked
  `"network": true` can use the network. Sharing the host's network would also share the X
  server's abstract socket, which a command could use to read keys or type into other windows,
  so with pasta (the passt package) installed they get a network namespace of their own.
  Without pasta they share your network only if that is what was approved (SHARED below);
  otherwise they don't run.
- a list such as ["firejail", "--profile=pickit-widget", "--"]: put in front of `bash -c`.

Every mode fails closed: if the runner is missing or the setting is invalid, the command doesn't
run, and never falls back to running with full access.
"""

import shlex

from . import config

TIMEOUT = 20
HOST, RESTRICTED, CUSTOM, INVALID = "host", "restricted", "custom", "invalid"
# What an approval records (never a setting): the sandbox, with internet commands on the host's
# network because pasta isn't installed. More access than RESTRICTED, less than HOST.
SHARED = "restricted-shared-net"
FAILED = 126  # exit code when the runner refuses (missing or misconfigured); the command never ran

# Runs on the host (after flatpak-spawn in the Flatpak): sets up bubblewrap there.
# Arguments: <network 0|1> <may share the host's network 0|1> <command>.
_RESTRICTED = r'''
command -v bwrap >/dev/null 2>&1 || {
  echo "pickit: the restricted command runner needs bubblewrap (bwrap);" \
       "install it, or choose full access in Settings" >&2
  exit 126; }
net=$1; share=$2; cmd=$3
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
  [ "$share" = 1 ] || {
    echo "pickit: this command uses the internet, and without pasta (the passt package) it would" \
         "share your network; install passt, or approve the widget's commands again" >&2
    exit 126; }
  # The host's network: name resolution lives in /run on most systems, so bring back just that.
  [ -d /run/systemd/resolve ] && set -- "$@" --ro-bind /run/systemd/resolve /run/systemd/resolve
  case "$rc" in /run/systemd/resolve/*) ;; /run/*) [ -f "$rc" ] && set -- "$@" --ro-bind "$rc" "$rc" ;; esac
fi
# The command starts with these variables and no others: nothing else from Pickit's environment
# (API keys, tokens, session addresses) reaches it.
set -- bwrap "$@" --chdir "$HOME" --unshare-pid --unshare-ipc --unshare-uts \
  --unshare-cgroup-try --die-with-parent --new-session -- env -i "HOME=$HOME"
for v in PATH USER LOGNAME LANG LANGUAGE TZ TERM LC_ALL LC_CTYPE LC_MESSAGES LC_NUMERIC LC_TIME \
         LC_COLLATE LC_MONETARY LC_MEASUREMENT LC_PAPER LC_NAME LC_ADDRESS LC_TELEPHONE; do
  eval "[ -n \"\${$v+x}\" ]" && eval "set -- \"\$@\" \"$v=\${$v}\""
done
set -- "$@" bash -c "$cmd"
if [ -n "$pasta" ]; then
  exec pasta --config-net --quiet --dns-forward 169.254.1.53 -- "$@"
fi
exec "$@"
'''


_isolated: tuple[float, bool] | None = None


def network_isolated() -> bool:
    """Whether commands that use the internet get their own network namespace (pasta, from
    the passt package, is installed on the host); otherwise they share the host's network.
    Remembered for half a minute: approvals ask this often, and in the Flatpak it's a host call."""
    import subprocess
    import time

    from . import runtime
    global _isolated
    now = time.monotonic()
    if _isolated is None or now - _isolated[0] > 30:
        try:
            found = subprocess.run(runtime.host_argv(["sh", "-c", "command -v pasta"]), capture_output=True,
                                   timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            found = False
        _isolated = (now, found)
    return _isolated[1]


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


def policy(runner):
    """How commands run with `runner`, as an approval records it: HOST, RESTRICTED, SHARED,
    INVALID or the custom runner's own list."""
    m = mode(runner)
    if m == CUSTOM:
        return runner
    if m == RESTRICTED and not network_isolated():
        return SHARED
    return m


def argv(cmd: str, network: bool = False, runner=None, share_network: bool = False) -> list[str]:
    """The command line (before flatpak-spawn) that runs `cmd` the way `runner` says.
    `share_network`: the approval allows a restricted internet command on the host's network
    when pasta is missing; without it such a command is refused."""
    limit = ["timeout", "-k", "2", str(TIMEOUT)]
    m = mode(runner)
    if m == HOST:
        return [*limit, "bash", "-c", cmd]
    if m == RESTRICTED:
        return [*limit, "sh", "-c", _RESTRICTED, "pickit-restricted", "1" if network else "0",
                "1" if share_network else "0", cmd]
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
