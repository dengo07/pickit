import pytest

pytest.importorskip("gi")

from pickit.bridge import CommandRunner  # noqa: E402

COMMANDS = {
    "battery": {"cmd": "cat /sys/class/power_supply/BAT0/capacity", "interval": 10},
    "weather": {"cmd": "curl -s wttr.in", "interval": 1800},
    "playpause": {"cmd": "playerctl play-pause", "interval": 0},
}


def refreshed(max_interval):
    runner = CommandRunner(COMMANDS, deliver=lambda *_: None)
    ran = []
    runner.run = ran.append  # record instead of executing
    runner.refresh(max_interval)
    return sorted(ran)


def test_refresh_never_triggers_actions():
    assert refreshed(None) == ["battery", "weather"]


def test_power_refresh_skips_slow_commands():
    assert refreshed(300) == ["battery"]


def test_start_runs_periodic_commands_but_not_actions():
    runner = CommandRunner(COMMANDS, deliver=lambda *_: None)
    ran = []
    runner.run = ran.append
    runner.start()
    runner.stop()
    assert sorted(ran) == ["battery", "weather"]
