import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("gi")

HOLD = textwrap.dedent("""
    import sys, time
    from pickit import daemon
    print(daemon.acquire_instance_lock(), flush=True)
    time.sleep(float(sys.argv[1]))
""")


def run(tmp_path, seconds):
    env = {"PICKIT_DATA_HOME": str(tmp_path / "pickit-data"), "PATH": "/usr/bin:/bin", "PYTHONPATH": "."}
    return subprocess.Popen([sys.executable, "-c", HOLD, str(seconds)], stdout=subprocess.PIPE,
                            text=True, env=env)


def test_only_one_daemon_can_hold_the_lock(tmp_path):
    first = run(tmp_path, 5)
    assert first.stdout.readline().strip() == "True"
    second = run(tmp_path, 0)
    assert second.communicate(timeout=30)[0].strip() == "False"
    first.kill()
    first.wait()
    third = run(tmp_path, 0)
    assert third.communicate(timeout=30)[0].strip() == "True"  # released when the holder exits


def test_the_lock_records_the_running_version(tmp_path):
    from pickit import __version__
    lock = tmp_path / "pickit-data" / "pickit" / "daemon.lock"
    first = run(tmp_path, 5)
    assert first.stdout.readline().strip() == "True"
    assert lock.read_text() == __version__
    second = run(tmp_path, 0)  # a start that finds the daemon running...
    assert second.communicate(timeout=30)[0].strip() == "False"
    assert lock.read_text() == __version__, "...must not erase the running daemon's version"
    first.kill()
    first.wait()


@pytest.mark.parametrize("running, ours, replace", [
    ("", "1.5.3", True),          # daemons before 1.5.3 didn't record a version
    ("1.5.2", "1.5.3", True),
    ("1.5.3", "1.5.3", False),
    ("1.6.0", "1.5.3", False),    # never replace a newer one (an old AppImage next to the Flatpak)
    ("1.5.9", "1.5.10", True),
])
def test_only_older_daemons_are_replaced(running, ours, replace):
    from pickit.daemon import is_older
    assert is_older(running, ours) == replace
