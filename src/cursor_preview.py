import os
import threading
import gi
import gettext
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, GLib, Gdk, GdkPixbuf

_ = gettext.gettext

# Preview area display edge length (pixels), small images use NEAREST for scaling up, large images use BILINEAR for scaling down to maintain clarity
DISPLAY_PIXEL_SIZE = 128


def _cursor_image_to_pixbuf(cursor_image) -> GdkPixbuf.Pixbuf | None:
    """Convert win2xcur CursorImage to GdkPixbuf (BGRA -> RGBA)."""
    try:
        w = cursor_image.image.width
        h = cursor_image.image.height
        bgra = cursor_image.image.export_pixels(channel_map="BGRA")
    except Exception:
        return None
    if len(bgra) != w * h * 4:
        return None
    # BGRA -> RGBA（GdkPixbuf 使用 RGB/RGBA）
    rgba = bytearray(w * h * 4)
    for i in range(0, len(bgra), 4):
        rgba[i] = bgra[i + 2]
        rgba[i + 1] = bgra[i + 1]
        rgba[i + 2] = bgra[i]
        rgba[i + 3] = bgra[i + 3]
    return GdkPixbuf.Pixbuf.new_from_data(
        bytes(rgba),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        w,
        h,
        w * 4,
    )


def _pixbuf_for_display(pb: GdkPixbuf.Pixbuf, size: int = DISPLAY_PIXEL_SIZE) -> GdkPixbuf.Pixbuf:
    """Scale to preview size, small images use NEAREST for scaling up to prevent blurring, large images use BILINEAR for scaling down."""
    w, h = pb.get_width(), pb.get_height()
    if w == size and h == size:
        return pb
    if w <= size and h <= size:
        # No upper limit, scale up small cursors to size (e.g. 32→128)
        scale = max(1, min(size // w, size // h))
        nw, nh = w * scale, h * scale
        return pb.scale_simple(nw, nh, GdkPixbuf.InterpType.NEAREST)
    return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)


def load_cursor_frames(
    cursor_path: str,
) -> list[tuple[GdkPixbuf.Pixbuf, float]] | None:
    """
    Load .cursor file, return (pixbuf, delay_sec) list at maximum available size.
    Use maximum size to avoid blurring from scaling up small images; multiple frames play continuously by delay.
    """
    try:
        from win2xcur.parser import open_blob
    except ImportError:
        return None
    if not os.path.isfile(cursor_path):
        return None
    with open(cursor_path, "rb") as f:
        blob = f.read()
    if blob[:4] != b"Xcur":
        return None
    try:
        cursor = open_blob(blob)
    except Exception:
        return None
    if not cursor.frames:
        return None
    first_frame = cursor.frames[0]
    if not first_frame.images:
        return None
    # Use maximum available size in file, avoid blurring from scaling up small images
    available = {img.nominal for img in first_frame.images}
    size = max(available)
    result = []
    for frame in cursor.frames:
        img = next((i for i in frame.images if i.nominal == size), frame.images[0])
        pb = _cursor_image_to_pixbuf(img)
        if pb is None:
            continue
        # Use file's actual frame interval, only avoid exception from 0
        delay = float(frame.delay) if frame.delay > 0 else 0.01
        result.append((_pixbuf_for_display(pb), delay))
    return result if result else None


def list_cursor_files_hierarchical(cursors_dir: str) -> list[tuple[str, list[str]]]:
    """
    List Xcursor files in directory: real files are level 1, symbolic links pointing to them are level 2.
    Returns [(real_name, [symlink_name, ...]), ...], sorted by real_name.
    """
    if not os.path.isdir(cursors_dir):
        return []
    # real_basename -> list of entry names that point to it (self or symlinks)
    real_to_names: dict[str, list[str]] = {}
    for name in os.listdir(cursors_dir):
        path = os.path.join(cursors_dir, name)
        if not os.path.isfile(path):
            continue
        real = path
        while os.path.islink(real):
            base = os.path.dirname(real)
            real = os.path.normpath(os.path.join(base, os.readlink(real)))
        if not os.path.isfile(real):
            continue
        real_name = os.path.basename(real)
        try:
            with open(real, "rb") as f:
                if f.read(4) != b"Xcur":
                    continue
        except Exception:
            continue
        if real_name not in real_to_names:
            real_to_names[real_name] = []
        # Real file itself goes first, symbolic link names follow
        if name == real_name:
            real_to_names[real_name].insert(0, name)
        else:
            if name not in real_to_names[real_name]:
                real_to_names[real_name].append(name)
    result = []
    for real_name in sorted(real_to_names.keys()):
        names = real_to_names[real_name]
        symlinks = sorted(set(n for n in names if n != real_name))
        result.append((real_name, symlinks))
    return result


class CursorPreviewDialog(Adw.Dialog):
    """Cursor preview dialog: left list shows cursor names, right shows animated preview (multi-frame continuous playback)."""

    def __init__(self, cursors_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.cursors_dir = cursors_dir
        self._timeout_id = None
        self._frames: list[tuple[GdkPixbuf.Pixbuf, float]] = []
        self._frame_index = 0
        self.set_title(_("Preview Cursors"))
        self.set_content_width(520)
        self.set_content_height(420)

        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.append(Adw.HeaderBar())

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main.set_margin_top(12)
        main.set_margin_bottom(12)
        main.set_margin_start(12)
        main.set_margin_end(12)
        main.set_vexpand(True)

        # Left: real files use ExpanderRow (collapsed by default), symbolic links are sub-rows
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.set_size_request(160, -1)
        list_box.add_css_class("boxed-list")
        list_box.connect("row-selected", self._on_list_row_selected)
        self._list_box = list_box

        scroll_list = Gtk.ScrolledWindow()
        scroll_list.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_list.set_child(list_box)
        scroll_list.set_vexpand(True)
        main.append(scroll_list)

        # Right: preview area, force image to occupy DISPLAY_PIXEL_SIZE display
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_hexpand(True)
        right.set_size_request(DISPLAY_PIXEL_SIZE + 32, DISPLAY_PIXEL_SIZE + 32)
        self._preview_image = Gtk.Image()
        self._preview_image.set_pixel_size(DISPLAY_PIXEL_SIZE)  # Force preview area size, avoid being compressed
        self._preview_image.set_vexpand(True)
        self._preview_image.set_halign(Gtk.Align.CENTER)
        self._preview_image.set_valign(Gtk.Align.CENTER)
        right.append(self._preview_image)
        self._preview_label = Gtk.Label(label=_("Select cursor on the left to preview"))
        self._preview_label.add_css_class("dim-label")
        right.append(self._preview_label)
        main.append(right)

        wrap.append(main)
        self.set_child(wrap)
        self._fill_list()

    def _fill_list(self):
        items = list_cursor_files_hierarchical(self.cursors_dir)
        first_expander = None
        for real_name, symlinks in items:
            expander = Adw.ExpanderRow()
            expander.set_title(real_name)
            expander.set_expanded(False)  # Collapsed by default
            expander.cursor_path = os.path.join(self.cursors_dir, real_name)
            self._list_box.append(expander)
            if first_expander is None:
                first_expander = expander
            # Level 2: symbolic links (use click gesture, because activated may not trigger inside ExpanderRow)
            for sym_name in symlinks:
                sub = Adw.ActionRow()
                sub.set_title(sym_name)
                sub.set_activatable(True)
                sub.cursor_path = os.path.join(self.cursors_dir, sym_name)
                click = Gtk.GestureClick()
                click.connect("released", self._on_child_row_clicked, sub)
                sub.add_controller(click)
                expander.add_row(sub)
        if first_expander:
            self._list_box.select_row(first_expander)
            self._show_preview_for_path(first_expander.cursor_path, first_expander.get_title())

    def _on_list_row_selected(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        """Level 1 (ExpanderRow) selected, preview corresponding real file."""
        if row is None:
            return
        path = getattr(row, "cursor_path", None)
        if not path:
            return
        name = row.get_title() if hasattr(row, "get_title") else ""
        self._show_preview_for_path(path, name)

    def _on_child_row_clicked(self, gesture, n_press, x, y, row):
        """Level 2 (symbolic link) clicked, preview."""
        path = getattr(row, "cursor_path", None)
        if not path:
            return
        name = row.get_title() if hasattr(row, "get_title") else ""
        self._show_preview_for_path(path, name)

    def _show_preview_for_path(self, path: str, name: str = ""):
        self._stop_animation()
        if not name:
            name = os.path.basename(path)
        self._preview_label.set_label(name)
        self._preview_image.clear()
        self._load_path = path
        self._load_name = name

        def do_load():
            frames = load_cursor_frames(path) or []
            GLib.idle_add(self._apply_loaded_frames, path, name, frames)

        threading.Thread(target=do_load, daemon=True).start()

    def _apply_loaded_frames(self, path: str, name: str, frames: list):
        """Main thread: apply background loaded frames (ignore if switched)."""
        if getattr(self, "_load_path", None) != path:
            return
        self._frames = frames
        if not self._frames:
            self._preview_image.clear()
            self._preview_label.set_label(_("{}\n(Cannot parse or not Xcursor)").format(name))
            return
        self._frame_index = 0
        self._preview_image.set_from_pixbuf(self._frames[0][0])
        if len(self._frames) > 1:
            self._start_animation()
        self._preview_label.set_label(name)

    def _start_animation(self):
        self._stop_animation()
        if len(self._frames) <= 1:
            return
        delay_sec = self._frames[self._frame_index][1]
        ms = max(1, int(delay_sec * 1000))  # Use pointer built-in interval, only avoid 0

        def tick():
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            pixbuf, delay_sec = self._frames[self._frame_index]
            self._preview_image.set_from_pixbuf(pixbuf)
            ms = max(1, int(delay_sec * 1000))
            self._timeout_id = GLib.timeout_add(ms, tick)
            return False

        self._timeout_id = GLib.timeout_add(ms, tick)

    def _stop_animation(self):
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def close(self):
        self._stop_animation()
        super().close()
