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
    env = {"XDG_DATA_HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": "."}
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
