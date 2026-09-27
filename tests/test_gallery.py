"""The shipped gallery: every item is a valid widget whose preview data covers what it shows."""

import json

import pytest

from pickit import gallery, generator
from pickit.native import data as D

ITEMS = gallery.items()
# Fields that are legitimately absent in the sample (shown only in other states).
OPTIONAL = {"battery-ring": {"battery.full"}}


def test_there_is_a_gallery():
    assert len(ITEMS) >= 10
    assert len({i.id for i in ITEMS}) == len(ITEMS)
    assert [i.order for i in ITEMS] == sorted(i.order for i in ITEMS)


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i.id)
def test_item_is_valid_and_complete(item):
    assert item.description and item.category
    assert generator.validate(item.spec, item.spec["engine"]) == item.spec
    assert set(item.sample) <= set(item.spec["commands"]), "sample for an undeclared command"
    periodic = {k for k, c in item.spec["commands"].items() if c["interval"] > 0}
    assert periodic <= set(item.sample), "every data command needs sample output for the preview"


def _paths(node):
    """Every `{path|filters}` data path used in a component tree."""
    text = json.dumps(node)
    return {m.split("|")[0].strip() for m in D.TEMPLATE.findall(text)}


@pytest.mark.parametrize("item", [i for i in ITEMS if i.sample], ids=lambda i: i.id)
def test_sample_covers_every_field(item):
    data = {}
    for key, outputs in item.sample.items():
        data[key] = D.parse_output(outputs[-1] if isinstance(outputs, list) else outputs)
    missing = {p for p in _paths(item.spec["ui"])
               if p.split(".")[0] in data and D.lookup(data, p) is None} - OPTIONAL.get(item.id, set())
    assert not missing, f"fields not in the sample output (typo?): {sorted(missing)}"
