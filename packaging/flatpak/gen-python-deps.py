#!/usr/bin/env python3
"""Regenerate python-deps.json: pinned wheels (URL + sha256) of `anthropic` for the
Flatpak runtime's Python, so the Flatpak builds offline as Flathub requires.

Usage: packaging/flatpak/gen-python-deps.py [python-version, default 3.14]
"""
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PYVER = sys.argv[1] if len(sys.argv) > 1 else "3.14"
ABI = "cp" + PYVER.replace(".", "")
OUT = Path(__file__).with_name("python-deps.json")

with tempfile.TemporaryDirectory() as tmp:
    subprocess.run([sys.executable, "-m", "pip", "download", "anthropic", "-d", tmp, "-q",
                    "--only-binary=:all:", "--no-cache-dir", "--python-version", PYVER,
                    "--implementation", "cp", "--abi", ABI,
                    "--platform", "manylinux_2_28_x86_64", "--platform", "manylinux_2_17_x86_64",
                    "--platform", "manylinux2014_x86_64", "--platform", "any"], check=True)
    wheels = sorted(p.name for p in Path(tmp).glob("*.whl"))

sources = []
for wheel in wheels:
    name, version = wheel.split("-")[:2]
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json") as r:
        release = json.load(r)
    match = next(u for u in release["urls"] if u["filename"] == wheel)
    sources.append({"type": "file", "url": match["url"], "sha256": match["digests"]["sha256"]})

module = {
    "name": "python-deps",
    "buildsystem": "simple",
    "build-commands": ["pip3 install --no-index --no-deps --no-build-isolation --prefix=/app *.whl"],
    "sources": sources,
}
OUT.write_text(json.dumps(module, indent=2) + "\n")
print(f"wrote {OUT} ({len(sources)} wheels)")
