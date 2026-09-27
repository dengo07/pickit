"""Ready-made widgets that work without any AI backend (pickit/gallery/*.json).

Each file is a normal widget spec plus a "gallery" object:
    {"order": 10, "category": "Time", "description": "...",
     "sample": {"<command key>": "<output>" or ["<output>", ...]}}
`sample` is shown in previews instead of running the commands, so browsing the gallery
never runs anything. A list of outputs is delivered in order (it fills sparklines).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import generator

GALLERY_DIR = Path(__file__).parent / "gallery"


@dataclass
class Item:
    id: str
    spec: dict
    description: str = ""
    category: str = ""
    order: int = 0
    sample: dict = field(default_factory=dict)


def items() -> list[Item]:
    result = []
    for path in GALLERY_DIR.glob("*.json"):
        raw = json.loads(path.read_text())
        meta = raw.get("gallery") or {}
        spec = generator.validate({k: v for k, v in raw.items() if k != "gallery"})
        result.append(Item(path.stem, spec, meta.get("description", ""), meta.get("category", ""),
                           int(meta.get("order", 0)), meta.get("sample") or {}))
    return sorted(result, key=lambda i: (i.order, i.id))
