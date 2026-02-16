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

"""光标转换模块"""

import os
from typing import Callable

from .constants import WIN_TO_XCURSOR, SYMLINK_MAP


class CursorConverter:
    """光标转换器"""

    def __init__(self, log_callback: Callable[[str], None] = None):
        """
        初始化转换器

        Args:
            log_callback: 日志回调函数，接收字符串参数
        """
        self.log = log_callback or (lambda msg: None)

    def convert_cursor(
        self,
        cursor_file: str,
        output_file: str,
        xcursor_name: str,
        target_sizes: list[int],
        add_shadow: bool = False,
        inf_dir: str | None = None,
    ) -> bool:
        """
        转换单个光标文件

        Args:
            cursor_file: 光标文件路径或文件名
            output_file: 输出文件路径
            target_sizes: 目标尺寸列表
            add_shadow: 是否添加阴影
            inf_dir: INF 文件所在目录（用于查找光标文件）

        Returns:
            是否转换成功
        """
        try:
            from win2xcur.parser import open_blob
            from win2xcur.writer import to_x11
            from win2xcur.shadow import apply_to_frames as add_shadow_to_frames
            from win2xcur.scale import apply_to_frames as scale_to_frames
        except ImportError:
            self.log("✗ 未找到 win2xcur 模块")
            self.log("请安装: pip install win2xcur")
            return False

        # 查找光标文件（在 INF 同级目录查找，不区分大小写）
        actual_cursor_file = None
        filename_lower = cursor_file.lower()

        # 如果 cursor_file 是完整路径且存在，直接使用
        if os.path.exists(cursor_file):
            actual_cursor_file = cursor_file
        elif inf_dir:
            # 只在 INF 同级目录查找
            for file in os.listdir(inf_dir):
                if file.lower() == filename_lower:
                    actual_cursor_file = os.path.join(inf_dir, file)
                    break

        if not actual_cursor_file or not os.path.exists(actual_cursor_file):
            self.log(f"✗ 未找到文件: {cursor_file}")
            return False

        try:
            # 读取光标数据（保留用于多次解析）
            with open(actual_cursor_file, "rb") as f:
                cursor_data = f.read()

            # 首次解析，检测原文件中已有的尺寸
            cursor = open_blob(cursor_data)
            original_sizes = set()
            for frame in cursor.frames:
                for image in frame.images:
                    original_sizes.add(image.nominal)
            self.log(f"  原文件尺寸: {','.join(str(x) for x in sorted(original_sizes))}")

            # 为每个目标尺寸生成帧
            all_frames = []
            for target_size in target_sizes:
                # 每次都重新解析原始数据（避免 deepcopy 问题）
                cursor_temp = open_blob(cursor_data)

                if target_size in original_sizes:
                    # 原文件中已有该尺寸，直接提取对应尺寸的帧
                    size_frames = []
                    for frame in cursor_temp.frames:
                        # 只保留目标尺寸的 images
                        matching_images = [img for img in frame.images if img.nominal == target_size]
                        if matching_images:
                            # 创建新帧，只包含该尺寸的图像
                            from win2xcur.cursor import CursorFrame
                            new_frame = CursorFrame(images=matching_images, delay=frame.delay)
                            size_frames.append(new_frame)
                    self.log(f"  使用原始 {target_size}x{target_size} ({len(size_frames)} 帧)")
                else:
                    # 需要缩放生成
                    size_frames = cursor_temp.frames

                    # 计算缩放比例：目标尺寸 / 原始尺寸
                    if original_sizes:
                        original_size = max(original_sizes)  # 使用最大的原始尺寸
                        scale_ratio = target_size / original_size
                        scale_to_frames(size_frames, scale=scale_ratio)

                        # 修正 nominal 值（apply_to_frames 不会自动更新它）
                        for frame in size_frames:
                            for image in frame.images:
                                image.nominal = target_size

                        self.log(f"  缩放生成 {target_size}x{target_size} (从 {original_size}x{original_size}, {len(size_frames)} 帧)")
                    else:
                        self.log(f"  ✗ 无法生成 {target_size}x{target_size}：原文件无有效尺寸")
                        continue

                # 如果需要，添加阴影（模拟 Windows 光标阴影，参数为相对比例）
                if add_shadow:
                    add_shadow_to_frames(
                        size_frames,
                        color="black",
                        radius=0.08,
                        sigma=0.04,
                        xoffset=0.02,
                        yoffset=0.02,
                    )

                all_frames.extend(size_frames)

            # 转换为 X11 格式
            x11_data = to_x11(all_frames)

            # 写入文件
            with open(output_file, "wb") as f:
                f.write(x11_data)

            self.log(f"  ✓ 生成包含 {len(target_sizes)} 个尺寸的光标文件")
            return True

        except Exception as e:
            self.log(f"✗ 转换失败 {cursor_file}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_symlinks(self, cursors_dir: str) -> int:
        """
        创建符号链接

        Args:
            cursors_dir: 光标目录路径

        Returns:
            创建的符号链接数量
        """
        created = 0
        for source, links in SYMLINK_MAP.items():
            for link_name in links:
                link_path = os.path.join(cursors_dir, link_name)
                try:
                    if os.path.exists(link_path):
                        os.remove(link_path)
                    os.symlink(source, link_path)
                    created += 1
                except Exception:
                    pass  # 忽略链接创建失败

        self.log(f"✓ 创建了 {created} 个符号链接")
        return created

    def create_index_theme(self, output_dir: str, theme_name: str) -> bool:
        """
        创建 index.theme 文件

        Args:
            output_dir: 输出目录
            theme_name: 主题名称

        Returns:
            是否创建成功
        """
        index_path = os.path.join(output_dir, "index.theme")
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"[Icon Theme]\n")
                f.write(f"Name={theme_name}\n")
                f.write(f"Comment=Converted from Windows cursor theme\n")
                f.write(f"Example=default\n")
            self.log(f"✓ 创建 index.theme")
            return True
        except Exception as e:
            self.log(f"创建 index.theme 失败: {e}")
            return False
