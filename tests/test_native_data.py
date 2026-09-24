import datetime

from pickit.native import data as d

DATA = {
    "battery": d.parse_output("capacity=77\nstatus=Not charging"),
    "stats": d.parse_output("cpu=8.0\nmem=45.1 7078 15708"),
    "w": d.parse_output('{"days": [{"max": 21, "date": "2026-09-25"}], "city": "Ankara"}'),
    "text": d.parse_output("just some text"),
    "now": datetime.datetime(2026, 9, 24, 21, 5, 7),
}


def test_parse_output_formats():
    assert DATA["battery"] == {"capacity": "77", "status": "Not charging"}
    assert DATA["w"]["days"][0]["max"] == 21
    assert DATA["text"] == "just some text"
    assert d.parse_output("[1, 2]") == [1, 2]
    assert d.parse_output("{not json") == "{not json"


def test_templates_and_filters():
    r = lambda t: d.resolve(t, DATA)  # noqa: E731
    assert r("{battery.capacity}%") == "77%"
    assert r("{stats.cpu}") == "8.0"  # a whole-template reference keeps the raw value
    assert r("{stats.mem|word:1|div:1024|round:1} GB") == "6.9 GB"
    assert r("{w.days.0.max}°") == "21°"
    assert r("{w.days.0.date|time:%a}") == "Fri"
    assert r("{w.city|upper}") == "ANKARA"
    assert r("{now|time:%H:%M:%S}") == "21:05:07"
    assert r("{missing.deep|default:--}") == "--"
    assert r("{w.days.9.max|default:?}") == "?"
    assert r("{text|truncate:6}") == "just …"
    assert r("no templates") == "no templates"


def test_conditions():
    c = lambda e: d.condition(e, DATA)  # noqa: E731
    assert c("{battery.status} == 'Not charging'")
    assert c("{battery.capacity} >= 77 and {battery.capacity} < 80")
    assert c("{battery.capacity} == 77%")
    assert not c("{battery.capacity} < 20 or {w.city} != Ankara")
    assert c("not {missing}")
    assert c("({stats.cpu} > 50) or {battery.capacity} == 77")


def test_choices_pick_first_match_then_default():
    color = [{"when": "{battery.capacity} < 20", "value": "#f00"},
             {"when": "{battery.status} == 'Not charging'", "value": "#0af"}, "#4ade80"]
    assert d.resolve(color, DATA) == "#0af"
    assert d.resolve(color[:1] + ["#4ade80"], DATA) == "#4ade80"


def test_hostile_input_is_just_data():
    for expr in ('__import__("os").system("touch /tmp/pwned")', "{a} == (", "1 +* 2", "{" * 50, "x" * 5000):
        assert d.condition(expr, DATA) in (True, False)
        d.resolve(expr, DATA)
    assert d.resolve("{battery.capacity|__class__}", DATA) == "77"  # unknown filters are ignored


def test_refs_find_data_dependencies():
    assert d.refs("{battery.capacity}% {now|time:%H}") == {"battery", "now"}
    assert d.refs([{"when": "{cpu} > 1", "value": "{w.city}"}, "x"]) == {"cpu", "w"}
