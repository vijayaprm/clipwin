# clipwin

A reliable, Windows-style (`Super+V`) clipboard history popup for GNOME on Wayland.

## Why

The obvious approach — [`cliphist`](https://github.com/sentriz/cliphist) +
`wl-paste --watch` — turns out **not to work on GNOME at all**: watch mode
needs the wlroots `zwlr_data_control` Wayland protocol, which GNOME's
compositor (Mutter) doesn't implement (only wlroots-based compositors like
Sway/Hyprland do).

GNOME's own `GPaste` shell extension *does* track clipboard history reliably
(it hooks GNOME Shell's clipboard APIs directly, in-process, so it isn't
affected by that protocol gap). But GPaste's own popup UI and its internal
paste-back path are broken for images on current GNOME Shell versions — text
pastes fine, images silently fail.

`clipwin` splits the difference: it lets GPaste's daemon do what it's
reliably good at (tracking), and replaces only the broken part — reads
history over GPaste's D-Bus API (text) and straight off its on-disk image
cache (`~/.local/share/gpaste/images/`), then writes the selected item back
to the clipboard itself via `wl-copy`, sidestepping GPaste's buggy paste code
entirely.

## What it is

- `clipwin-popup.py` — a GTK4 popup window: search history, click a text or
  image entry to copy it back to the clipboard, delete individual entries,
  or clear everything. Bound to `Super+V`.
- `install.sh` — installs dependencies, makes sure GPaste's tracking bits are
  enabled (its own popup/keybinding are unused), and wires `Super+V` to
  `clipwin-popup` via a GNOME custom keybinding.

## Install

```sh
./install.sh
```

## Usage

Press `Super+V` anywhere. Click an item to paste it. Trash icon removes one
entry, "Clear all" wipes history.

## Uninstall

```sh
rm ~/.local/bin/clipwin-popup ~/.local/share/applications/clipwin.desktop
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "[]"
```
