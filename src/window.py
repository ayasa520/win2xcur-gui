# MIT License
#
# Copyright (c) 2026 Unknown
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# SPDX-License-Identifier: MIT

"""主窗口模块"""

import os
import sys
import zipfile
import tempfile
import shutil
import re
import threading
import queue
from pathlib import Path

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GObject

from .constants import WIN_TO_XCURSOR
from .models import ThemeNameModel
from .inf_parser import INFParser
from .converter import CursorConverter
from .cursor_preview import CursorPreviewDialog


class Win2xcurGuiWindow(Adw.ApplicationWindow):
    """主窗口"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title("Windows 光标主题转换工具")
        self.set_default_size(800, 600)

        # 创建主布局
        self.setup_ui()

        # 状态变量
        self.zip_path = None
        self.temp_dir = None
        self.inf_parser = None
        self.inf_dir = None  # INF 文件所在目录
        self.output_dir = None  # 输出目录

        # 初始化转换器
        self.converter = CursorConverter(log_callback=self.log)

    def setup_ui(self):
        """设置用户界面"""
        # 主容器
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # 标题栏
        header = Adw.HeaderBar()
        main_box.append(header)

        # 使用 Stack 管理多个页面
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        main_box.append(self.stack)

        # ===== 页面 1: 欢迎页（StatusPage + 拖放） =====
        welcome_page = self.create_welcome_page()
        self.stack.add_named(welcome_page, "welcome")

        # ===== 页面 2: 配置页 =====
        config_page = self.create_config_page()
        self.stack.add_named(config_page, "config")

        # 默认显示欢迎页
        self.stack.set_visible_child_name("welcome")

    def create_welcome_page(self):
        """创建欢迎页面"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_vexpand(True)

        # StatusPage
        status = Adw.StatusPage()
        status.set_icon_name("folder-download-symbolic")
        status.set_title("Windows 光标主题转换工具")
        status.set_description("拖入 ZIP 压缩包或点击按钮选择文件\n支持 .cur 和 .ani 格式")
        page.append(status)

        # 按钮容器
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(20)
        page.append(button_box)

        # 选择文件按钮
        select_btn = Gtk.Button(label="选择 ZIP 文件")
        select_btn.add_css_class("pill")
        select_btn.add_css_class("suggested-action")
        select_btn.connect("clicked", self.on_select_file)
        button_box.append(select_btn)

        # 设置拖放目标
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_file_dropped)
        page.add_controller(drop_target)

        return page

    def create_config_page(self):
        """创建配置页面"""
        # 滚动容器
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        # 内容区域
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)
        scroll.set_child(content)

        # 文件信息
        file_group = Adw.PreferencesGroup()
        file_group.set_title("当前文件")
        content.append(file_group)

        self.file_info_row = Adw.ActionRow()
        self.file_info_row.set_title("未选择文件")

        change_btn = Gtk.Button(label="更换文件")
        change_btn.set_valign(Gtk.Align.CENTER)
        change_btn.connect("clicked", self.on_select_file)
        self.file_info_row.add_suffix(change_btn)
        file_group.add(self.file_info_row)

        # 信息显示区域
        info_group = Adw.PreferencesGroup()
        info_group.set_title("主题信息")
        content.append(info_group)

        theme_name_row = Adw.ActionRow()
        theme_name_row.set_title("主题名称")
        self.theme_name_entry = Gtk.Entry()
        self.theme_name_entry.set_placeholder_text("未命名主题")
        self.theme_name_entry.set_hexpand(True)
        self.theme_name_entry.set_valign(Gtk.Align.CENTER)
        self.theme_name_model = ThemeNameModel()
        self.theme_name_entry.bind_property(
            "text",
            self.theme_name_model,
            "theme-name",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        self.theme_name_model.connect("notify::theme-name", self._on_theme_name_notify)
        theme_name_row.add_suffix(self.theme_name_entry)
        info_group.add(theme_name_row)

        self.cursor_count_row = Adw.ActionRow()
        self.cursor_count_row.set_title("光标数量")
        self.cursor_count_row.set_subtitle("--")
        info_group.add(self.cursor_count_row)

        # 选项区域
        options_group = Adw.PreferencesGroup()
        options_group.set_title("转换选项")
        content.append(options_group)

        shadow_row = Adw.ActionRow()
        shadow_row.set_title("添加阴影效果")
        shadow_row.set_subtitle("模拟 Windows 光标阴影")
        self.shadow_switch = Gtk.Switch()
        self.shadow_switch.set_valign(Gtk.Align.CENTER)
        shadow_row.add_suffix(self.shadow_switch)
        shadow_row.set_activatable_widget(self.shadow_switch)
        options_group.add(shadow_row)

        symlink_row = Adw.ActionRow()
        symlink_row.set_title("创建符号链接")
        symlink_row.set_subtitle("为常见光标名称创建符号链接")
        self.symlink_switch = Gtk.Switch()
        self.symlink_switch.set_active(True)
        self.symlink_switch.set_valign(Gtk.Align.CENTER)
        symlink_row.add_suffix(self.symlink_switch)
        symlink_row.set_activatable_widget(self.symlink_switch)
        options_group.add(symlink_row)

        # 多尺寸选项
        size_row = Adw.ExpanderRow()
        size_row.set_title("生成多尺寸光标")
        size_row.set_subtitle("选择要生成的尺寸（可多选）")
        options_group.add(size_row)

        # 24x24
        size24_row = Adw.ActionRow()
        size24_row.set_title("24×24")
        self.size24_check = Gtk.CheckButton()
        self.size24_check.set_valign(Gtk.Align.CENTER)
        size24_row.add_suffix(self.size24_check)
        size24_row.set_activatable_widget(self.size24_check)
        size_row.add_row(size24_row)

        # 32x32
        size32_row = Adw.ActionRow()
        size32_row.set_title("32×32")
        self.size32_check = Gtk.CheckButton()
        self.size32_check.set_active(True)
        self.size32_check.set_valign(Gtk.Align.CENTER)
        size32_row.add_suffix(self.size32_check)
        size32_row.set_activatable_widget(self.size32_check)
        size_row.add_row(size32_row)

        # 48x48
        size48_row = Adw.ActionRow()
        size48_row.set_title("48×48")
        self.size48_check = Gtk.CheckButton()
        self.size48_check.set_valign(Gtk.Align.CENTER)
        size48_row.add_suffix(self.size48_check)
        size48_row.set_activatable_widget(self.size48_check)
        size_row.add_row(size48_row)

        # 64x64
        size64_row = Adw.ActionRow()
        size64_row.set_title("64×64")
        self.size64_check = Gtk.CheckButton()
        self.size64_check.set_active(True)
        self.size64_check.set_valign(Gtk.Align.CENTER)
        size64_row.add_suffix(self.size64_check)
        size64_row.set_activatable_widget(self.size64_check)
        size_row.add_row(size64_row)

        # 96x96
        size96_row = Adw.ActionRow()
        size96_row.set_title("96×96")
        self.size96_check = Gtk.CheckButton()
        self.size96_check.set_valign(Gtk.Align.CENTER)
        size96_row.add_suffix(self.size96_check)
        size96_row.set_activatable_widget(self.size96_check)
        size_row.add_row(size96_row)

        # 128x128
        size128_row = Adw.ActionRow()
        size128_row.set_title("128×128")
        self.size128_check = Gtk.CheckButton()
        self.size128_check.set_active(True)
        self.size128_check.set_valign(Gtk.Align.CENTER)
        size128_row.add_suffix(self.size128_check)
        size128_row.set_activatable_widget(self.size128_check)
        size_row.add_row(size128_row)

        # 256x256
        size256_row = Adw.ActionRow()
        size256_row.set_title("256×256")
        self.size256_check = Gtk.CheckButton()
        self.size256_check.set_valign(Gtk.Align.CENTER)
        size256_row.add_suffix(self.size256_check)
        size256_row.set_activatable_widget(self.size256_check)
        size_row.add_row(size256_row)

        # 输出目录选择
        output_row = Adw.ActionRow()
        output_row.set_title("输出目录")
        self.output_label = Gtk.Label(label="/tmp/<主题名>")
        self.output_label.add_css_class("dim-label")
        output_row.add_suffix(self.output_label)

        output_btn = Gtk.Button(label="选择目录")
        output_btn.connect("clicked", self.on_select_output)
        output_row.add_suffix(output_btn)
        options_group.add(output_row)

        # 日志区域（最上）
        log_group = Adw.PreferencesGroup()
        log_group.set_title("转换日志")
        content.append(log_group)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_vexpand(True)
        log_scroll.set_min_content_height(200)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD)
        log_scroll.set_child(self.log_view)
        log_group.add(log_scroll)
        log_buf = self.log_view.get_buffer()
        log_buf.create_mark("log_end", log_buf.get_end_iter(), False)
        self._log_queue = queue.Queue()

        # 进度条：日志下面、按钮上面
        progress_clamp = Adw.Clamp()
        progress_clamp.set_maximum_size(400)
        progress_clamp.set_margin_top(12)
        progress_clamp.set_margin_bottom(8)
        progress_clamp.set_visible(False)
        content.append(progress_clamp)

        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        progress_clamp.set_child(progress_box)

        self.progress_label = Gtk.Label()
        self.progress_label.add_css_class("title-4")
        progress_box.append(self.progress_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_start(20)
        self.progress_bar.set_margin_end(20)
        progress_box.append(self.progress_bar)

        self.progress_clamp = progress_clamp

        # 按钮：最下面（转换进行时隐藏）
        self.button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.button_box.set_halign(Gtk.Align.CENTER)
        self.button_box.set_margin_top(10)
        content.append(self.button_box)

        self.convert_btn = Gtk.Button(label="开始转换")
        self.convert_btn.add_css_class("suggested-action")
        self.convert_btn.add_css_class("pill")
        self.convert_btn.set_sensitive(False)
        self.convert_btn.connect("clicked", self.on_convert)
        self.button_box.append(self.convert_btn)

        self.preview_btn = Gtk.Button(label="查看光标")
        self.preview_btn.add_css_class("pill")
        self.preview_btn.set_sensitive(False)
        self.preview_btn.connect("clicked", self.on_preview_cursors)
        self.button_box.append(self.preview_btn)

        self.apply_btn = Gtk.Button(label="安装主题")
        self.apply_btn.add_css_class("pill")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", self.on_install_theme)
        self.button_box.append(self.apply_btn)

        return scroll

    def log(self, message: str):
        """线程安全：将消息放入队列，由主线程统一写入 TextView。"""
        self._log_queue.put_nowait(message)
        GLib.idle_add(self._flush_log_queue)

    def _flush_log_queue(self):
        """主线程 only：从队列取出所有待写日志，一次性插入并滚动到底部。"""
        messages = []
        try:
            while True:
                messages.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        if not messages:
            return
        buffer = self.log_view.get_buffer()
        mark = buffer.get_mark("log_end")
        if mark:
            it = buffer.get_iter_at_mark(mark)
            text = "\n".join(messages) + "\n"
            buffer.insert(it, text)
            self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def on_file_dropped(self, drop_target, value, x, y):
        """处理拖放的文件"""
        if isinstance(value, Gio.File):
            file_path = value.get_path()
            if file_path and file_path.lower().endswith('.zip'):
                self.zip_path = file_path
                self.file_info_row.set_title(os.path.basename(file_path))
                self.log(f"已选择文件: {self.zip_path}")

                # 更换文件后重置输出目录，使输出路径重新随主题名变化
                self.output_dir = None

                # 切换到配置页面
                self.stack.set_visible_child_name("config")

                # 解析 ZIP 文件
                self.parse_zip()
                return True
        return False

    def on_select_file(self, button):
        """选择 ZIP 文件"""
        dialog = Gtk.FileDialog()
        dialog.set_title("选择光标主题压缩包")

        # 设置文件过滤器
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name("ZIP 压缩包")
        zip_filter.add_pattern("*.zip")

        all_filter = Gtk.FileFilter()
        all_filter.set_name("所有文件")
        all_filter.add_pattern("*")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zip_filter)
        filters.append(all_filter)
        dialog.set_filters(filters)

        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        """文件选择完成"""
        try:
            file = dialog.open_finish(result)
            if file:
                self.zip_path = file.get_path()
                self.file_info_row.set_title(os.path.basename(self.zip_path))
                self.log(f"已选择文件: {self.zip_path}")

                # 更换文件后重置输出目录，使输出路径重新随主题名变化
                self.output_dir = None

                # 切换到配置页面
                self.stack.set_visible_child_name("config")

                # 解析 ZIP 文件
                self.parse_zip()
        except GLib.Error as e:
            if e.code != 2:  # 2 = dismissed
                self.log(f"错误: {e.message}")

    def detect_zip_encoding(self, zip_path):
        """检测 ZIP 文件的编码"""
        with zipfile.ZipFile(zip_path, "r") as z:
            for info in z.infolist():
                if info.flag_bits & 0x800:
                    return "utf-8"
            return "gbk"

    def parse_zip(self):
        """解析 ZIP 文件"""
        try:
            # 清理旧的临时目录
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)

            # 创建临时目录
            self.temp_dir = tempfile.mkdtemp(prefix="win2xcur_")

            if not self.zip_path:
                self.log("错误: 未选择文件")
                return

            # 检测 ZIP 编码
            encoding = self.detect_zip_encoding(self.zip_path)
            self.log(f"检测到 ZIP 编码: {encoding.upper()}")

            # 解压 ZIP
            self.log("正在解压文件...")
            with zipfile.ZipFile(self.zip_path, "r") as zip_ref:
                if encoding == "gbk":
                    # 使用 GBK 编码解压
                    for member in zip_ref.namelist():
                        try:
                            member_name = member.encode('cp437').decode('gbk')
                        except Exception:
                            member_name = member

                        # 提取文件
                        source = zip_ref.open(member)
                        target_path = os.path.join(self.temp_dir, member_name)

                        # 如果是目录
                        if member_name.endswith('/'):
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                else:
                    # UTF-8 编码，直接解压
                    zip_ref.extractall(self.temp_dir)

            # 查找 INF 文件
            inf_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith(".inf"):
                        inf_files.append(os.path.join(root, file))

            if not inf_files:
                self.log("错误: 未找到 INF 文件")
                return

            # 使用第一个 INF 文件
            inf_path = inf_files[0]
            self.inf_dir = os.path.dirname(inf_path)  # 保存 INF 所在目录
            self.log(f"找到 INF 文件: {os.path.basename(inf_path)}")

            # 解析 INF
            self.inf_parser = INFParser(inf_path)
            if self.inf_parser.parse():
                self.cursor_count_row.set_subtitle(
                    str(len(self.inf_parser.cursor_files))
                )
                self.log(f"主题名称: {self.inf_parser.theme_name}")
                self.log(f"找到 {len(self.inf_parser.cursor_files)} 个光标")
                # 主题名：GObject 属性，已与 Entry 绑定，这里只设初始值
                self.theme_name_model.set_property("theme-name", self.inf_parser.theme_name)

                # 未手动选择输出目录时，显示默认路径
                if not self.output_dir:
                    self.output_label.set_text(f"/tmp/{self.get_theme_name_for_path()}")

                # 显示光标映射
                for win_type, filename in self.inf_parser.cursor_files.items():
                    xcursor_name = WIN_TO_XCURSOR.get(win_type, win_type)
                    self.log(f"  {win_type} -> {xcursor_name}: {filename}")

                self.convert_btn.set_sensitive(True)
            else:
                self.log("错误: 无法解析 INF 文件")

        except Exception as e:
            self.log(f"解析错误: {e}")
            import traceback
            traceback.print_exc()

    def _on_theme_name_notify(self, obj, pspec):
        """主题名称属性变化时更新默认输出路径显示"""
        if not self.output_dir and self.inf_parser:
            name = self.get_theme_name_for_path() or "未命名主题"
            self.output_label.set_text(f"/tmp/{name}")

    def get_theme_name(self):
        """当前主题名称：来自与 Entry 绑定的 GObject 属性。"""
        name = (self.theme_name_model.get_property("theme-name") or "").strip()
        return name if name else "未命名主题"

    def get_theme_name_for_path(self):
        """获取用于路径的主题名（去除非法字符）"""
        name = self.get_theme_name()
        return re.sub(r'[/\\:*?"<>|]', '_', name) or "未命名主题"

    def on_select_output(self, button):
        """选择输出目录"""
        dialog = Gtk.FileDialog()
        dialog.set_title("选择输出目录")
        dialog.select_folder(self, None, self.on_output_selected)

    def on_output_selected(self, dialog, result):
        """输出目录选择完成"""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.output_dir = folder.get_path()
                self.output_label.set_text(self.output_dir)
                self.log(f"输出目录: {self.output_dir}")
        except GLib.Error as e:
            if e.code != 2:
                self.log(f"错误: {e.message}")

    def on_convert(self, button):
        """开始转换"""
        if not self.inf_parser:
            self.log("错误: 未选择主题文件")
            return

        # 确定输出目录（默认使用 /tmp）
        if not self.output_dir:
            self.output_dir = os.path.join("/tmp", self.get_theme_name_for_path())

        cursors_dir = os.path.join(self.output_dir, "cursors")
        os.makedirs(cursors_dir, exist_ok=True)

        self.log(f"\n开始转换到: {cursors_dir}")
        self.button_box.set_visible(False)
        self.progress_clamp.set_visible(True)
        self.progress_bar.set_fraction(0.0)
        self.progress_label.set_text("准备转换...")

        # 检查 win2xcur 是否可用
        try:
            from win2xcur.parser import open_blob
            from win2xcur.writer import to_x11

            self.log("✓ 找到 win2xcur 模块")
        except ImportError:
            self.log("✗ 未找到 win2xcur 模块")
            self.log("请安装: pip install win2xcur")
            self.progress_clamp.set_visible(False)
            self.button_box.set_visible(True)
            self.convert_btn.set_sensitive(True)
            return

        # 在后台线程中执行转换，避免阻塞 UI
        def run():
            self._do_conversion_worker(cursors_dir)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _update_ui_progress(self, fraction: float, text: str):
        """在主线程更新进度条和标签（仅由 GLib.idle_add 调用）"""
        self.progress_bar.set_fraction(fraction)
        self.progress_label.set_text(text)

    def _do_conversion_worker(self, cursors_dir):
        """在后台线程中执行的实际转换逻辑"""
        try:
            # 获取用户选择的目标尺寸
            target_sizes = []
            if self.size24_check.get_active():
                target_sizes.append(24)
            if self.size32_check.get_active():
                target_sizes.append(32)
            if self.size48_check.get_active():
                target_sizes.append(48)
            if self.size64_check.get_active():
                target_sizes.append(64)
            if self.size96_check.get_active():
                target_sizes.append(96)
            if self.size128_check.get_active():
                target_sizes.append(128)
            if self.size256_check.get_active():
                target_sizes.append(256)

            if not target_sizes:
                self.log("✗ 请至少选择一个目标尺寸")
                GLib.idle_add(self._on_conversion_error)
                return

            self.log(f"目标尺寸: {', '.join(str(s) for s in target_sizes)}")

            total = len(self.inf_parser.cursor_files)
            converted = 0
            add_shadow = self.shadow_switch.get_active()

            for win_type, filename in self.inf_parser.cursor_files.items():
                xcursor_name = WIN_TO_XCURSOR.get(win_type)
                if not xcursor_name:
                    self.log(f"跳过未映射的类型: {win_type}")
                    continue

                output_file = os.path.join(cursors_dir, xcursor_name)

                # 进度更新到主线程
                frac = (converted + 1) / total
                GLib.idle_add(
                    lambda f=frac, cn=converted+1, tot=total, fn=filename:
                    self._update_ui_progress(f, f"正在转换 {cn}/{tot}: {fn}")
                )
                self.log(f"转换: {filename} -> {xcursor_name}")

                # 使用转换器进行转换
                success = self.converter.convert_cursor(
                    cursor_file=filename,
                    output_file=output_file,
                    xcursor_name=xcursor_name,
                    target_sizes=target_sizes,
                    add_shadow=add_shadow,
                    inf_dir=self.inf_dir,
                )

                if success:
                    converted += 1
                    GLib.idle_add(
                        lambda c=converted, t=total:
                        self._update_ui_progress(c / t, f"正在转换 {c}/{t}")
                    )

            # 创建符号链接
            if self.symlink_switch.get_active():
                GLib.idle_add(
                    lambda c=converted, t=total:
                    self._update_ui_progress(c / t if t else 1.0, "正在创建符号链接...")
                )
                self.log("\n创建符号链接...")
                self.converter.create_symlinks(cursors_dir)

            # 创建 index.theme
            GLib.idle_add(
                lambda: self._update_ui_progress(1.0, "正在创建主题配置...")
            )
            self.converter.create_index_theme(self.output_dir, self.get_theme_name())

            self.log(f"\n✓ 转换完成! 成功转换 {converted}/{total} 个光标")
            self.log(f"主题位置: {self.output_dir}")
            self.log("\n转换完成！如需安装到系统，请点击【安装主题】按钮")

            GLib.idle_add(self._on_conversion_done)

        except Exception as e:
            self.log(f"\n✗ 转换过程出错: {e}")
            import traceback
            traceback.print_exc()
            GLib.idle_add(self._on_conversion_error)

    def _on_conversion_done(self):
        """转换成功，在主线程恢复 UI"""
        self.progress_clamp.set_visible(False)
        self.button_box.set_visible(True)
        self.convert_btn.set_sensitive(True)
        self.preview_btn.set_sensitive(True)
        self.apply_btn.set_sensitive(True)

    def _on_conversion_error(self):
        """转换出错，在主线程恢复 UI"""
        self.progress_clamp.set_visible(False)
        self.button_box.set_visible(True)
        self.convert_btn.set_sensitive(True)
        self.preview_btn.set_sensitive(False)
        self.apply_btn.set_sensitive(False)

    def on_preview_cursors(self, button):
        """打开光标预览对话框（参考 xcursor-viewer，动态指针按动态图连续播放）"""
        if not self.output_dir:
            self.log("错误: 请先完成转换")
            return
        cursors_dir = os.path.join(self.output_dir, "cursors")
        if not os.path.isdir(cursors_dir):
            self.log("错误: 未找到 cursors 目录")
            return
        dialog = CursorPreviewDialog(cursors_dir=cursors_dir)
        dialog.present(self)

    def on_install_theme(self, button):
        """安装主题到用户图标目录（仅复制文件，不修改系统/桌面主题设置）"""
        if not self.inf_parser or not self.output_dir:
            self.log("错误: 请先转换主题")
            return

        self.apply_btn.set_sensitive(False)
        self.log("\n开始安装主题到系统...")

        data_home = os.environ.get(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local/share")
        )

        icons_dir = os.path.join(data_home, "icons")

        os.makedirs(icons_dir, exist_ok=True)

        target_dir = os.path.join(icons_dir, self.get_theme_name_for_path())

        try:
            # 如果目标已存在，先删除
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)

            # 复制主题文件
            self.log(f"复制主题到: {target_dir}")
            shutil.copytree(self.output_dir, target_dir, symlinks=True)
            self.log("✓ 主题已安装，请在系统设置中手动选择该光标主题")

            self.apply_btn.set_sensitive(True)

        except Exception as e:
            self.log(f"✗ 安装失败: {e}")
            import traceback
            traceback.print_exc()
            self.apply_btn.set_sensitive(True)

    def do_close_request(self):
        """窗口关闭时清理"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
        return False
