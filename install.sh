#!/usr/bin/env bash
# Run Pickit from this source checkout: adds it to your application menu.
# (Not needed for the Flatpak or AppImage releases.)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ID=io.github.dengo07.Pickit
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"

python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')" 2>/dev/null || {
  echo "Missing system packages. On Debian/Ubuntu/Mint run:"
  echo "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
  exit 1
}
python3 -c "import gi; gi.require_version('GtkLayerShell','0.1')" 2>/dev/null || {
  echo "Optional, for native Wayland widgets on KDE, Hyprland, Sway and similar:"
  echo "  sudo apt install gir1.2-gtklayershell-0.1"
}
install -Dm644 "$DIR/pickit/data/$APP_ID.svg" "$SHARE/icons/hicolor/scalable/apps/$APP_ID.svg"
sed "s|^Exec=pickit|Exec=env PYTHONPATH=$DIR python3 -m pickit|" "$DIR/pickit/data/$APP_ID.desktop" \
  > "$SHARE/applications/$APP_ID.desktop"
# Double-clicking a .pickit widget file opens it in Pickit.
install -Dm644 "$DIR/pickit/data/$APP_ID.mime.xml" "$SHARE/mime/packages/$APP_ID.xml"
update-mime-database "$SHARE/mime" 2>/dev/null || true
update-desktop-database "$SHARE/applications" 2>/dev/null || true
echo "Installed. Open \"Pickit\" from your application menu."
