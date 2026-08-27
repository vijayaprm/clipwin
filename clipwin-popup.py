#!/usr/bin/env python3
"""
clipwin: a Windows-like (Win+V) clipboard history popup for GNOME/Wayland.

Backend: the GPaste daemon (org.gnome.GPaste D-Bus service) + GNOME Shell
extension do the actual clipboard *tracking* reliably (they hook GNOME
Shell's own clipboard APIs, so they work regardless of Wayland protocol
support). This script only renders the popup UI and talks to GPaste over
D-Bus for history/content, then writes the selected item back to the
clipboard itself via `wl-copy` — bypassing GPaste's own paste-back path,
which is broken for images on newer GNOME Shell versions.
"""
import subprocess
import sys
import os
import xml.etree.ElementTree as ET

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib

MAX_TEXT_PREVIEW = 120
BUS_NAME = "org.gnome.GPaste"
OBJ_PATH = "/org/gnome/GPaste"
IFACE = "org.gnome.GPaste2"
HISTORY_XML = os.path.expanduser("~/.local/share/gpaste/history.xml")


def _proxy():
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
        BUS_NAME, OBJ_PATH, IFACE, None,
    )


def get_history(proxy):
    """Returns list of (uuid, kind, preview), newest first."""
    result = proxy.call_sync("GetHistory", None, Gio.DBusCallFlags.NONE, -1, None)
    pairs = result.unpack()[0]  # a(ss)
    items = []
    for uuid, preview in pairs:
        kind = proxy.call_sync(
            "GetElementKind", GLib.Variant("(s)", (uuid,)),
            Gio.DBusCallFlags.NONE, -1, None,
        ).unpack()[0]
        items.append((uuid, kind, preview))
    return items


def get_text(proxy, uuid):
    result = proxy.call_sync(
        "GetElement", GLib.Variant("(s)", (uuid,)),
        Gio.DBusCallFlags.NONE, -1, None,
    )
    return result.unpack()[0]


def get_image_path(uuid):
    if not os.path.exists(HISTORY_XML):
        return None
    tree = ET.parse(HISTORY_XML)
    for item in tree.getroot().findall("item"):
        if item.get("uuid") == uuid and item.get("kind") == "Image":
            value = item.find("value")
            if value is not None and value.text:
                return value.text.strip()
    return None


def delete_item(proxy, uuid):
    proxy.call_sync("Delete", GLib.Variant("(s)", (uuid,)), Gio.DBusCallFlags.NONE, -1, None)


def empty_history(proxy):
    proxy.call_sync("EmptyHistory", GLib.Variant("(s)", ("history",)), Gio.DBusCallFlags.NONE, -1, None)


class ClipwinWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipboard History")
        self.set_default_size(420, 520)
        self.proxy = _proxy()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                          margin_top=8, margin_bottom=4, margin_start=10, margin_end=10)
        title = Gtk.Label(label="Clipboard History", xalign=0)
        title.add_css_class("title-4")
        header.append(title)
        header.append(Gtk.Box(hexpand=True))
        clear_btn = Gtk.Button(label="Clear all")
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", self.on_clear_all)
        header.append(clear_btn)
        root.append(header)

        self.search = Gtk.SearchEntry(margin_start=10, margin_end=10, margin_bottom=6)
        self.search.connect("search-changed", self.on_search_changed)
        root.append(self.search)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        root.append(scroller)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_start(10)
        self.listbox.set_margin_end(10)
        self.listbox.set_margin_bottom(10)
        scroller.set_child(self.listbox)

        self._all_items = []
        self.reload()

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key)
        self.add_controller(key_ctrl)

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self.on_focus_leave)
        self.add_controller(focus_ctrl)

    def on_focus_leave(self, *_a):
        GLib.timeout_add(150, self._maybe_close_on_blur)

    def _maybe_close_on_blur(self):
        if not self.is_active():
            self.close()
        return False

    def on_key(self, _ctrl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def reload(self):
        try:
            self._all_items = get_history(self.proxy)
        except GLib.Error as e:
            self._all_items = []
            print(f"clipwin: failed to read GPaste history: {e}", file=sys.stderr)
        self.populate(self._all_items)

    def on_search_changed(self, entry):
        q = entry.get_text().lower().strip()
        if not q:
            self.populate(self._all_items)
            return
        filtered = [i for i in self._all_items if q in i[2].lower()]
        self.populate(filtered)

    def populate(self, items):
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        if not items:
            row = Gtk.ListBoxRow(activatable=False)
            row.set_child(Gtk.Label(label="No clipboard history yet", margin_top=20, margin_bottom=20))
            self.listbox.append(row)
            return

        for uuid, kind, preview in items:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                            margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
            row.set_child(hbox)

            if kind == "Image":
                path = get_image_path(uuid)
                pix = self._thumbnail_for(path) if path else None
                if pix:
                    img = Gtk.Picture.new_for_pixbuf(pix)
                    img.set_size_request(64, 64)
                    img.set_content_fit(Gtk.ContentFit.COVER)
                    hbox.append(img)
                label = Gtk.Label(label="[Image]", xalign=0)
            else:
                text = preview.strip()
                if len(text) > MAX_TEXT_PREVIEW:
                    text = text[:MAX_TEXT_PREVIEW] + "…"
                label = Gtk.Label(label=text, xalign=0, wrap=True)

            label.set_hexpand(True)
            hbox.append(label)

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.connect("clicked", self.on_delete_clicked, uuid)
            hbox.append(del_btn)

            click = Gtk.GestureClick()
            click.connect("released", self.on_row_clicked, uuid, kind)
            row.add_controller(click)

            self.listbox.append(row)

    def _thumbnail_for(self, path):
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file(path)
            return pix.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
        except GLib.Error:
            return None

    def on_row_clicked(self, _gesture, _n_press, _x, _y, uuid, kind):
        if kind == "Image":
            path = get_image_path(uuid)
            if not path or not os.path.exists(path):
                print(f"clipwin: image file missing for {uuid}", file=sys.stderr)
                return
            with open(path, "rb") as f:
                data = f.read()
            proc = subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=subprocess.PIPE)
        else:
            data = get_text(self.proxy, uuid).encode("utf-8")
            proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        proc.communicate(input=data)
        self.close()

    def on_delete_clicked(self, _btn, uuid):
        delete_item(self.proxy, uuid)
        self.reload()

    def on_clear_all(self, _btn):
        empty_history(self.proxy)
        self.reload()


class ClipwinApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.local.Clipwin",
                          flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_activate(self):
        if self.win and self.win.get_visible():
            self.win.close()
            self.win = None
            return
        self.win = ClipwinWindow(self)
        self.win.present()

    def do_command_line(self, _cmdline):
        self.activate()
        return 0


if __name__ == "__main__":
    app = ClipwinApp()
    sys.exit(app.run(sys.argv))
