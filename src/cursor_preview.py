import os
import threading
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, GLib, Gdk, GdkPixbuf


# 预览区显示边长（像素），小图用 NEAREST 放大、大图用 BILINEAR 缩小以保持清晰
DISPLAY_PIXEL_SIZE = 128


def _cursor_image_to_pixbuf(cursor_image) -> GdkPixbuf.Pixbuf | None:
    """将 win2xcur CursorImage 转为 GdkPixbuf（BGRA -> RGBA）。"""
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
    """缩放到预览尺寸，小图用 NEAREST 放大防模糊，大图用 BILINEAR 缩小。"""
    w, h = pb.get_width(), pb.get_height()
    if w == size and h == size:
        return pb
    if w <= size and h <= size:
        # 不设上限，小光标放大到 size（如 32→128）
        scale = max(1, min(size // w, size // h))
        nw, nh = w * scale, h * scale
        return pb.scale_simple(nw, nh, GdkPixbuf.InterpType.NEAREST)
    return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)


def load_cursor_frames(
    cursor_path: str,
) -> list[tuple[GdkPixbuf.Pixbuf, float]] | None:
    """
    加载 .cursor 文件，返回最大可用尺寸下的 (pixbuf, delay_sec) 列表。
    用最大尺寸避免放大小图导致模糊；多帧按 delay 连续播放。
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
    # 使用文件中可用的最大尺寸，避免用小图放大导致模糊
    available = {img.nominal for img in first_frame.images}
    size = max(available)
    result = []
    for frame in cursor.frames:
        img = next((i for i in frame.images if i.nominal == size), frame.images[0])
        pb = _cursor_image_to_pixbuf(img)
        if pb is None:
            continue
        # 使用文件中的真实帧间隔，仅避免 0 导致定时异常
        delay = float(frame.delay) if frame.delay > 0 else 0.01
        result.append((_pixbuf_for_display(pb), delay))
    return result if result else None


def list_cursor_files_hierarchical(cursors_dir: str) -> list[tuple[str, list[str]]]:
    """
    列出目录下的 Xcursor：真实文件为一级，指向它的符号链接为二级。
    返回 [(real_name, [symlink_name, ...]), ...]，按 real_name 排序。
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
        # 真实文件本身放第一个，符号链接名随后
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
    """光标预览对话框：左侧列表光标名，右侧为动态图预览（多帧连续播放）。"""

    def __init__(self, cursors_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.cursors_dir = cursors_dir
        self._timeout_id = None
        self._frames: list[tuple[GdkPixbuf.Pixbuf, float]] = []
        self._frame_index = 0
        self.set_title("预览光标")
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

        # 左侧：真实文件用 ExpanderRow（默认折叠），符号链接为子行
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

        # 右侧：预览区，强制图片占 DISPLAY_PIXEL_SIZE 显示
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_hexpand(True)
        right.set_size_request(DISPLAY_PIXEL_SIZE + 32, DISPLAY_PIXEL_SIZE + 32)
        self._preview_image = Gtk.Image()
        self._preview_image.set_pixel_size(DISPLAY_PIXEL_SIZE)  # 强制预览区尺寸，避免被压小
        self._preview_image.set_vexpand(True)
        self._preview_image.set_halign(Gtk.Align.CENTER)
        self._preview_image.set_valign(Gtk.Align.CENTER)
        right.append(self._preview_image)
        self._preview_label = Gtk.Label(label="选择左侧光标以预览")
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
            expander.set_expanded(False)  # 默认折叠
            expander.cursor_path = os.path.join(self.cursors_dir, real_name)
            self._list_box.append(expander)
            if first_expander is None:
                first_expander = expander
            # 二级：符号链接（用点击手势，因在 ExpanderRow 内 activated 可能不触发）
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
        """一级（ExpanderRow）被选中时预览对应真实文件。"""
        if row is None:
            return
        path = getattr(row, "cursor_path", None)
        if not path:
            return
        name = row.get_title() if hasattr(row, "get_title") else ""
        self._show_preview_for_path(path, name)

    def _on_child_row_clicked(self, gesture, n_press, x, y, row):
        """二级（符号链接）被点击时预览。"""
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
        """主线程：应用后台加载的帧（若已切换则忽略）。"""
        if getattr(self, "_load_path", None) != path:
            return
        self._frames = frames
        if not self._frames:
            self._preview_image.clear()
            self._preview_label.set_label(f"{name}\n（无法解析或非 Xcursor）")
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
        ms = max(1, int(delay_sec * 1000))  # 以指针内置间隔为准，仅避免 0

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
