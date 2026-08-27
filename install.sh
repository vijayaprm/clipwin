#!/usr/bin/env bash
# clipwin installer — a reliable Win+V-style clipboard history for GNOME/Wayland.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

echo "==> Checking system dependencies (wl-clipboard, GPaste)"
MISSING=""
command -v wl-copy >/dev/null 2>&1 || MISSING="$MISSING wl-clipboard"
command -v gpaste-client >/dev/null 2>&1 || MISSING="$MISSING gnome-shell-extension-gpaste"
if [[ -n "$MISSING" ]]; then
  echo "    missing:$MISSING — installing via apt (needs sudo)"
  sudo apt-get install -y $MISSING
else
  echo "    already installed, skipping"
fi

echo "==> Installing popup script"
mkdir -p "$BIN_DIR"
install -m 755 "$SCRIPT_DIR/clipwin-popup.py" "$BIN_DIR/clipwin-popup"

echo "==> Installing desktop entry"
mkdir -p "$APP_DIR"
install -m 644 "$SCRIPT_DIR/clipwin.desktop" "$APP_DIR/clipwin.desktop"
sed -i "s|Exec=clipwin-popup|Exec=$BIN_DIR/clipwin-popup|" "$APP_DIR/clipwin.desktop"

echo "==> Ensuring GPaste is unmasked and its tracking extension is enabled"
# GPaste is used purely as the clipboard *tracker* (via its GNOME Shell
# extension + daemon, which hook Shell's own clipboard APIs). Its own popup
# UI and keybinding grab are NOT used — clipwin-popup replaces those.
systemctl --user unmask org.gnome.GPaste.service 2>/dev/null || true
gnome-extensions enable GPaste@gnome-shell-extensions.gnome.org 2>/dev/null || true
gpaste-client daemon-reexec >/dev/null 2>&1 || true

echo "==> Wiring up Super+V shortcut"
BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/clipwin-popup/"
OLD_GPASTE_BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/gpaste-popup/"

EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
# drop the old gpaste-popup entry and any existing clipwin-popup entry (idempotent re-run), then add clipwin-popup
CLEANED=$(python3 - "$EXISTING" "$OLD_GPASTE_BASE" "$BASE" <<'PY'
import sys, ast
existing, old, base = sys.argv[1], sys.argv[2], sys.argv[3]
items = [] if existing.strip() == "@as []" else ast.literal_eval(existing)
items = [i for i in items if i not in (old, base)]
print(items)
PY
)

if [[ "$CLEANED" == "[]" ]]; then
  NEW="['$BASE']"
else
  NEW=$(python3 -c "print($CLEANED + ['$BASE'])")
fi

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE" name "Clipwin Clipboard History"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE" command "$BIN_DIR/clipwin-popup"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE" binding "<Super>v"

echo "==> Done. Press Super+V to open clipboard history."
