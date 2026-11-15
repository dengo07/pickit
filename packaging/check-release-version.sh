#!/bin/sh
# Fails unless the tag being released matches the code it points at: `__version__`, a
# CHANGELOG section and a metainfo <release>. Run by the release workflow before anything is
# built, so a tag pushed onto the wrong commit (v1.5.3 was put on the 1.5.2 code) can't publish.
# Usage: packaging/check-release-version.sh v1.5.4
set -eu
tag=${1:?usage: check-release-version.sh vX.Y.Z}
want=${tag#v}
cd "$(dirname "$0")/.."
have=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' pickit/__init__.py)
ok=1
if [ "$have" != "$want" ]; then
  echo "error: tag $tag is on code that says __version__ = \"$have\" (pickit/__init__.py)." >&2
  echo "       Merge the version bump first, then tag the merged commit." >&2
  ok=0
fi
if ! grep -q "^## \[$want\]" CHANGELOG.md; then
  echo "error: CHANGELOG.md has no \"## [$want]\" section." >&2
  ok=0
fi
if ! grep -q "<release version=\"$want\"" pickit/data/io.github.dengo07.Pickit.metainfo.xml; then
  echo "error: the metainfo file has no <release version=\"$want\"> entry." >&2
  ok=0
fi
[ "$ok" = 1 ] || exit 1
echo "ok: $tag matches __version__, CHANGELOG.md and the metainfo file"
