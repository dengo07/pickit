#!/usr/bin/env bash
# Builds dist/Pickit-x86_64.AppImage: Python, GTK3, WebKitGTK and every library
# they need, taken from this (Debian/Ubuntu-family) build machine. Only the libraries on
# the AppImage excludelist (glibc, GPU drivers, X11, fonts, ...) come from the user's system.
#
# The AppImage runs on distros whose glibc is at least as new as the build machine's,
# so build on the oldest distro you want to support.
#
# Build deps: python3-gi python3-gi-cairo gir1.2-webkit2-4.1 glib-networking
#             librsvg2-common python3-pip rsync curl
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$ROOT/build/appimage"
TOOLS="$ROOT/build/tools"
DIST="$ROOT/dist"
APPDIR="$BUILD/AppDir"
U="$APPDIR/usr"
TRIPLET=x86_64-linux-gnu
SYSLIB=/usr/lib/$TRIPLET
L="$U/lib/$TRIPLET"
APP_ID=io.github.dengobey.Pickit
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
DATA="$ROOT/pickit/data"

for p in "$SYSLIB/libwebkit2gtk-4.1.so.0" "$SYSLIB/webkit2gtk-4.1/WebKitWebProcess" \
         /usr/lib/python3/dist-packages/gi /usr/lib/python3/dist-packages/cairo \
         "$SYSLIB/gio/modules/libgiognutls.so" "/usr/bin/python$PYVER"; do
  [ -e "$p" ] || { echo "Missing build dependency: $p" >&2; exit 1; }
done

echo "==> Fetching tools"
mkdir -p "$TOOLS"
[ -x "$TOOLS/appimagetool" ] || {
  curl -sSfL -o "$TOOLS/appimagetool" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOLS/appimagetool"; }
[ -f "$TOOLS/excludelist" ] || curl -sSfL -o "$TOOLS/excludelist" \
  https://raw.githubusercontent.com/AppImageCommunity/pkg2appimage/master/excludelist

rm -rf "$BUILD"
mkdir -p "$U/bin" "$L" "$U/lib/python3/dist-packages" "$U/share/pickit"

echo "==> Python $PYVER"
cp "/usr/bin/python$PYVER" "$U/bin/"
ln -s "python$PYVER" "$U/bin/python3"
rsync -a --exclude __pycache__ --exclude /test --exclude /idlelib --exclude /tkinter \
  --exclude /turtledemo --exclude /ensurepip --exclude /lib2to3 --exclude '/config-*' \
  --exclude /site-packages --exclude /dist-packages \
  "/usr/lib/python$PYVER/" "$U/lib/python$PYVER/"
rsync -a --exclude __pycache__ /usr/lib/python3/dist-packages/gi /usr/lib/python3/dist-packages/cairo \
  "$U/lib/python3/dist-packages/"
PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install -q --no-compile --only-binary=:all: \
  --target "$U/lib/python3/dist-packages" anthropic

echo "==> Pickit"
rsync -a --exclude __pycache__ "$ROOT/pickit" "$U/share/pickit/"

echo "==> GTK / WebKit runtime files"
rsync -a --exclude MiniBrowser "$SYSLIB/webkit2gtk-4.1" "$L/"
rsync -a "$SYSLIB/girepository-1.0" "$L/"
mkdir -p "$L/gio/modules"
cp "$SYSLIB/gio/modules/libgiognutls.so" "$L/gio/modules/"
PIXBUF="$L/gdk-pixbuf-2.0/2.10.0"
mkdir -p "$PIXBUF/loaders"
for loader in svg gif bmp ico xpm tga pnm ani; do
  f="$SYSLIB/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-$loader.so"
  [ -e "$f" ] && cp "$f" "$PIXBUF/loaders/"
done
mkdir -p "$U/share/glib-2.0/schemas"
cp /usr/share/glib-2.0/schemas/org.gtk.Settings.*.gschema.xml "$U/share/glib-2.0/schemas/"
glib-compile-schemas "$U/share/glib-2.0/schemas"

echo "==> Collecting shared libraries"
EXCLUDE=$(grep -v '^#' "$TOOLS/excludelist" | awk 'NF {print $1}'; printf '%s\n' libnvidia libcuda libvulkan.so.1)
is_excluded() {
  local name; name=$(basename "$1")
  while read -r pat; do [[ "$name" == "$pat"* ]] && return 0; done <<< "$EXCLUDE"
  return 1
}
roots=("$U/bin/python$PYVER" "$SYSLIB"/libgtk-3.so.0 "$SYSLIB"/libgdk-3.so.0
       "$SYSLIB"/libwebkit2gtk-4.1.so.0 "$SYSLIB"/libjavascriptcoregtk-4.1.so.0
       "$SYSLIB"/libsoup-3.0.so.0 "$SYSLIB"/libpangocairo-1.0.so.0 "$SYSLIB"/libgdk_pixbuf-2.0.so.0
       "$SYSLIB"/libatk-1.0.so.0 "$SYSLIB"/libcairo-gobject.so.2 "$SYSLIB"/librsvg-2.so.2)
mapfile -t more < <(find "$U/lib/python$PYVER/lib-dynload" "$U/lib/python3/dist-packages" "$L" \
                      -name '*.so*' -type f; find "$L/webkit2gtk-4.1" -type f -perm -u+x)
count=0
while read -r lib; do
  is_excluded "$lib" && continue
  dest="$L/$(basename "$lib")"
  [ -e "$dest" ] || { cp -L "$lib" "$dest"; count=$((count + 1)); }
done < <( { printf '%s\n' "${roots[@]}" | grep '\.so'; ldd "${roots[@]}" "${more[@]}" 2>/dev/null \
            | awk '/=> \// {print $3}'; } | sort -u)
echo "    bundled $count libraries"

echo "==> Relocating WebKit helper processes"
# libwebkit2gtk has its helper-process directory compiled in (no runtime override in
# release builds). Replace it with a same-length path relative to $APPDIR/usr, which AppRun
# makes the working directory.
python3 - "$L/libwebkit2gtk-4.1.so.0" <<'EOF'
import sys
path = sys.argv[1]
old = b"/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1"
tail = b"lib/x86_64-linux-gnu/webkit2gtk-4.1"
pad = len(old) - len(tail)  # filled with "./" (and one extra "/" if odd): same directory
new = b"./" * (pad // 2) + b"/" * (pad % 2) + tail
assert len(old) == len(new), (len(old), len(new))
data = open(path, "rb").read()
n = data.count(old)
assert n, "helper path not found in libwebkit2gtk"
open(path, "wb").write(data.replace(old, new))
print(f"    patched {n} occurrence(s)")
EOF

echo "==> Pixbuf loader cache"
GDK_PIXBUF_MODULEDIR="$PIXBUF/loaders" LD_LIBRARY_PATH="$L" \
  "$SYSLIB/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" | sed "s|$APPDIR|@APPDIR@|g" > "$PIXBUF/loaders.cache.in"

echo "==> Desktop integration files"
install -Dm644 "$DATA/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
install -Dm644 "$DATA/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
ln -s "$APP_ID.svg" "$APPDIR/.DirIcon"
install -Dm644 "$DATA/$APP_ID.desktop" "$U/share/applications/$APP_ID.desktop"
install -Dm644 "$DATA/$APP_ID.svg" "$U/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -Dm644 "$DATA/$APP_ID.metainfo.xml" "$U/share/metainfo/$APP_ID.appdata.xml"
install -Dm755 "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"

echo "==> Building AppImage"
mkdir -p "$DIST"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOLS/appimagetool" --no-appstream -n "$APPDIR" \
  "$DIST/Pickit-x86_64.AppImage" >/dev/null
ls -lh "$DIST/Pickit-x86_64.AppImage"
