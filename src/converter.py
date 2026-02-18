"""Cursor conversion module"""

import os
import gettext
import numpy as np
from typing import Callable

from .constants import WIN_TO_XCURSOR, SYMLINK_MAP

_ = gettext.gettext


class CursorConverter:
    """Cursor converter"""

    def __init__(self, log_callback: Callable[[str], None] = None):
        """
        Initialize converter

        Args:
            log_callback: log callback function, accepts string parameter
        """
        self.log = log_callback or (lambda msg: None)
        self._superres_model = None
        self._superres_scale = 4  # 默认放大倍率（会在实际推理后根据模型自动修正）
        self._superres_input_hw = None  # 模型期望的输入尺寸 (H, W)，None 表示可变尺寸

    def _load_superres_model(self):
        """加载超分辨率模型（懒加载，使用 ONNX Runtime + RealESRGAN）"""
        if self._superres_model is not None:
            return True

        try:
            import onnxruntime as ort
        except ImportError as e:
            self.log(_("✗ Super-resolution runtime not found: {}").format(str(e)))
            self.log(_("Please install: pip install onnxruntime"))
            return False

        try:
            model_path = self._download_superres_model()
            if not model_path:
                self.log(_("✗ Failed to prepare super-resolution model"))
                return False

            # 使用可用的 provider（在 Flatpak 中通常是 CPUExecutionProvider）
            sess_options = ort.SessionOptions()
            self._superres_model = ort.InferenceSession(
                model_path,
                sess_options=sess_options,
                providers=ort.get_available_providers(),
            )

            # 记录模型期望的输入尺寸（如果是固定尺寸的话）
            try:
                input_info = self._superres_model.get_inputs()[0]
                shape = input_info.shape  # e.g. [1, 3, 64, 64] 或 [1, 3, 'h', 'w']
                if (
                    isinstance(shape, (list, tuple))
                    and len(shape) == 4
                    and isinstance(shape[2], int)
                    and isinstance(shape[3], int)
                ):
                    self._superres_input_hw = (int(shape[2]), int(shape[3]))
                else:
                    self._superres_input_hw = None
            except Exception:
                self._superres_input_hw = None

            self.log(
                _("✓ Loaded super-resolution model: RealESRGAN x{}").format(
                    self._superres_scale
                )
            )
            return True
        except Exception as e:
            self.log(_("✗ Failed to load super-resolution model: {}").format(str(e)))
            return False

    def _download_superres_model(self) -> str | None:
        import urllib.request
        import hashlib

        model_url = "https://huggingface.co/imgdesignart/realesrgan-x4-onnx/resolve/138909edd364e7da67b5803c3918281e0428d19b/onnx/model.onnx"
        # 模型文件的预期 SHA256 校验和
        expected_sha256 = (
            "fa18ce70de3a55f3149d0cc898d335d2d69fca29edc0692cb362c856b2942c3f"
        )

        def verify_sha256(filepath: str, expected: str) -> bool:
            """验证文件的 SHA256 校验和"""
            try:
                sha256_hash = hashlib.sha256()
                with open(filepath, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                return sha256_hash.hexdigest() == expected
            except Exception:
                return False

        user_cache_dir = os.environ.get(
            "XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache")
        )
        cache_dir = os.path.join(user_cache_dir, "win2xcur-gui")
        os.makedirs(cache_dir, exist_ok=True)
        model_path = os.path.join(cache_dir, "realesrgan-x4.onnx")

        # 如果缓存文件存在，验证其完整性
        if os.path.exists(model_path):
            if verify_sha256(model_path, expected_sha256):
                return model_path
            else:
                self.log(_("  Cached model checksum mismatch, re-downloading..."))
                try:
                    os.remove(model_path)
                except Exception:
                    pass

        try:
            self.log(_("  Downloading super-resolution model (RealESRGAN x4)..."))
            urllib.request.urlretrieve(model_url, model_path)

            if not verify_sha256(model_path, expected_sha256):
                self.log(_("✗ Downloaded model checksum verification failed"))
                try:
                    os.remove(model_path)
                except Exception:
                    pass
                return None

            self.log(_("  ✓ Model downloaded and verified"))
            return model_path
        except Exception as e:
            self.log(_("✗ Failed to download model: {}").format(str(e)))
            return None

    def _apply_superres_to_image(self, img_array: np.ndarray) -> np.ndarray:
        """
        使用 RealESRGAN (ONNX) 对图像做超分辨率

        Args:
            img_array: numpy 数组，RGBA 或 RGB 格式，形状 (H, W, 3/4)

        Returns:
            超分后的 RGBA 或 RGB 数组
        """
        if self._superres_model is None:
            if not self._load_superres_model():
                return img_array

        try:
            # 拆分 RGB 和 alpha
            has_alpha = img_array.shape[2] == 4
            if has_alpha:
                rgb = img_array[:, :, :3]
                alpha = img_array[:, :, 3]
            else:
                rgb = img_array
                alpha = None

            # 如果模型期望固定输入尺寸，则先把 RGB 缩放到对应尺寸
            target_hw = getattr(self, "_superres_input_hw", None)
            if target_hw is not None:
                target_h, target_w = target_hw
                if rgb.shape[0] != target_h or rgb.shape[1] != target_w:
                    from PIL import Image

                    rgb_img = Image.fromarray(rgb)
                    rgb_img = rgb_img.resize(
                        (target_w, target_h), Image.Resampling.BICUBIC
                    )
                    rgb = np.asarray(rgb_img)

            # RealESRGAN ONNX 输入：NCHW、float32、0~1
            rgb_float = rgb.astype(np.float32) / 255.0
            input_tensor = np.transpose(rgb_float, (2, 0, 1))[None, ...]  # (1, 3, H, W)

            sess = self._superres_model
            if sess is None:
                return img_array
            input_name = sess.get_inputs()[0].name
            outputs = sess.run(None, {input_name: input_tensor})
            output = outputs[0]  # (1, 3, H', W')

            output_rgb = output[0]
            output_rgb = np.clip(output_rgb, 0.0, 1.0)
            output_rgb = (np.transpose(output_rgb, (1, 2, 0)) * 255.0).astype(np.uint8)

            # 处理 alpha：使用同样的缩放倍率做插值
            if alpha is not None:
                from PIL import Image

                h, w = output_rgb.shape[:2]
                alpha_img = Image.fromarray(alpha)
                alpha_upscaled = alpha_img.resize((w, h), Image.Resampling.LANCZOS)

                # 轻微锐化边缘（sigmoid）
                alpha_arr = np.asarray(alpha_upscaled).astype(np.float32) / 255.0
                alpha_sharpened = 1.0 / (1.0 + np.exp(-12 * (alpha_arr - 0.5)))
                alpha_out = (alpha_sharpened * 255).astype(np.uint8)

                output = np.dstack([output_rgb, alpha_out])
            else:
                output = output_rgb

            return output

        except Exception as e:
            self.log(_("✗ Super-resolution failed: {}").format(str(e)))
            import traceback

            traceback.print_exc()
            return img_array

    def convert_cursor(
        self,
        cursor_file: str,
        output_file: str,
        xcursor_name: str,
        target_sizes: list[int],
        add_shadow: bool = False,
        use_superres: bool = False,
        inf_dir: str | None = None,
    ) -> bool:
        """
        Convert single cursor file

        Args:
            cursor_file: cursor file path or filename
            output_file: output file path
            target_sizes: target size list
            add_shadow: whether to add shadow
            use_superres: whether to use super-resolution
            inf_dir: INF file directory (for finding cursor files)

        Returns:
            whether conversion succeeded
        """
        try:
            from win2xcur.parser import open_blob
            from win2xcur.writer import to_x11
            from win2xcur.shadow import apply_to_frames as add_shadow_to_frames
            from win2xcur.scale import apply_to_frames as scale_to_frames
        except ImportError:
            self.log(_("✗ win2xcur module not found"))
            self.log(_("Please install: pip install win2xcur"))
            return False

        # Find cursor file (search in INF same level directory, case insensitive)
        actual_cursor_file = None
        filename_lower = cursor_file.lower()

        # If cursor_file is a full path and exists, use directly
        if os.path.exists(cursor_file):
            actual_cursor_file = cursor_file
        elif inf_dir:
            # Only search in INF same level directory
            for file in os.listdir(inf_dir):
                if file.lower() == filename_lower:
                    actual_cursor_file = os.path.join(inf_dir, file)
                    break

        if not actual_cursor_file or not os.path.exists(actual_cursor_file):
            self.log(_("✗ File not found: {}").format(cursor_file))
            return False

        try:
            # Read cursor data (keep for multiple parsing)
            with open(actual_cursor_file, "rb") as f:
                cursor_data = f.read()

            # First parse, detect existing sizes in original file
            cursor = open_blob(cursor_data)
            original_sizes = set()
            for frame in cursor.frames:
                for image in frame.images:
                    original_sizes.add(image.nominal)
            self.log(
                _("  Original file sizes: {}").format(
                    ",".join(str(x) for x in sorted(original_sizes))
                )
            )

            # Generate frames for each target size (finally merge by frame index, not concatenate)
            base_frame_count = len(cursor.frames)
            merged_frames = []  # Final output: merge multiple sizes by frame

            # If super-resolution is enabled, generate super-resolved base frames
            if use_superres:
                from PIL import Image

                if not original_sizes:
                    self.log(
                        _(
                            "  ✗ Cannot use super-resolution: original file has no valid sizes"
                        )
                    )
                    return False

                # 先用最大原始尺寸作为参考，实际 superres_size 会在第一次推理后根据真实倍率修正
                max_original_size = max(original_sizes)
                superres_size = None
                scale_factor_global = None

                # Generate super-resolved frames
                superres_frames = []
                from win2xcur.cursor import CursorFrame

                for frame_idx in range(base_frame_count):
                    cursor_fresh = open_blob(cursor_data)
                    frame = cursor_fresh.frames[frame_idx]

                    # Get source size image - 必须是最大尺寸
                    img = next(
                        (i for i in frame.images if i.nominal == max_original_size),
                        None,
                    )
                    
                    # 如果该帧没有最大尺寸的图像，跳过这一帧
                    if img is None:
                        self.log(
                            _("  Skipping frame {} (no {}x{} size)").format(
                                frame_idx, max_original_size, max_original_size
                            )
                        )
                        continue
                    
                    # Convert to numpy array and apply super-resolution
                    img_array = np.array(img.image)
                    superres_array = self._apply_superres_to_image(img_array)

                    # 根据第一次成功的结果推断真实放大倍率和 superres_size
                    if scale_factor_global is None:
                        src_h = img_array.shape[0]
                        sr_h = superres_array.shape[0]
                        if src_h > 0:
                            scale_factor_global = sr_h / src_h
                            self._superres_scale = scale_factor_global
                            superres_size = int(
                                round(max_original_size * scale_factor_global)
                            )
                            self.log(
                                _("  Using super-resolution: {}x{} → {}x{}").format(
                                    max_original_size,
                                    max_original_size,
                                    superres_size,
                                    superres_size,
                                )
                            )

                    # Create new image from super-resolved array
                    superres_pil = Image.fromarray(superres_array)

                    # Convert PIL Image to wand Image to maintain compatibility
                    from wand.image import Image as WandImage
                    import io

                    img_buffer = io.BytesIO()
                    superres_pil.save(img_buffer, format="PNG")
                    img_buffer.seek(0)
                    superres_wand = WandImage(blob=img_buffer.getvalue())

                    # Scale hotspot（使用实际推断出的倍率）
                    scale_factor = scale_factor_global or self._superres_scale
                    new_hotspot = (
                        int(img.hotspot[0] * scale_factor),
                        int(img.hotspot[1] * scale_factor),
                    )

                    # Create new CursorImage with wand Image
                    from win2xcur.cursor import CursorImage

                    superres_cursor_img = CursorImage(
                        image=superres_wand,
                        hotspot=new_hotspot,
                        nominal=superres_size,
                    )

                    superres_frames.append(
                        CursorFrame(images=[superres_cursor_img], delay=frame.delay)
                    )

                self.log(
                    _(
                        "  ✓ Super-resolution complete, generating target sizes from {}x{}"
                    ).format(superres_size, superres_size)
                )

                # Now scale from super-resolved frames to all target sizes
                for target_size in target_sizes:
                    size_frames = []
                    scale_ratio = target_size / superres_size

                    for superres_frame in superres_frames:
                        if not superres_frame.images:
                            size_frames.append(
                                CursorFrame(images=[], delay=superres_frame.delay)
                            )
                        else:
                            # Scale from super-resolved image (now wand Image)
                            from win2xcur.cursor import CursorImage

                            scaled_images = []
                            for cursor_img in superres_frame.images:
                                # Clone the wand image
                                wand_img = cursor_img.image.clone()

                                # Resize using wand's resize method
                                new_width = int(wand_img.width * scale_ratio)
                                new_height = int(wand_img.height * scale_ratio)
                                wand_img.resize(new_width, new_height)

                                # Scale hotspot
                                new_hotspot = (
                                    int(cursor_img.hotspot[0] * scale_ratio),
                                    int(cursor_img.hotspot[1] * scale_ratio),
                                )

                                # Create new CursorImage
                                scaled_img = CursorImage(
                                    image=wand_img,
                                    hotspot=new_hotspot,
                                    nominal=target_size,
                                )
                                scaled_images.append(scaled_img)

                            size_frames.append(
                                CursorFrame(
                                    images=scaled_images, delay=superres_frame.delay
                                )
                            )

                    self.log(
                        _(
                            "  Scaled to generate {}x{} (from super-resolution, {} frames)"
                        ).format(target_size, target_size, len(size_frames))
                    )

                    # Add shadow if needed
                    if add_shadow:
                        add_shadow_to_frames(
                            size_frames,
                            color="black",
                            radius=0.08,
                            sigma=0.04,
                            xoffset=0.02,
                            yoffset=0.02,
                        )

                    # Merge into merged_frames by frame
                    if not merged_frames:
                        from win2xcur.cursor import CursorFrame

                        merged_frames = [
                            CursorFrame(images=list(fr.images), delay=fr.delay)
                            for fr in size_frames[:base_frame_count]
                        ]
                    else:
                        for idx in range(min(len(merged_frames), len(size_frames))):
                            merged_frames[idx].images.extend(size_frames[idx].images)

            else:
                # Original logic (without super-resolution)
                for target_size in target_sizes:
                    # Re-parse original data each time (avoid deepcopy issues)
                    cursor_temp = open_blob(cursor_data)

                    if target_size in original_sizes:
                        # Original file already has this size, directly extract frames of corresponding size
                        size_frames = []
                        for frame in cursor_temp.frames:
                            # Only keep images of target size
                            matching_images = [
                                img
                                for img in frame.images
                                if img.nominal == target_size
                            ]
                            if matching_images:
                                # Create new frame, only include images of this size
                                from win2xcur.cursor import CursorFrame

                                new_frame = CursorFrame(
                                    images=matching_images, delay=frame.delay
                                )
                                size_frames.append(new_frame)
                        self.log(
                            _("  Using original {}x{} ({} frames)").format(
                                target_size, target_size, len(size_frames)
                            )
                        )
                    else:
                        # Need to scale to generate: only take one image from source size (maximum size), avoid scaling multiple sizes together
                        if not original_sizes:
                            self.log(
                                _(
                                    "  ✗ Cannot generate {}x{}: original file has no valid sizes"
                                ).format(target_size, target_size)
                            )
                            continue

                        from win2xcur.cursor import CursorFrame

                        original_size = max(
                            original_sizes
                        )  # Use maximum original size as source
                        size_frames = []
                        scale_ratio = target_size / original_size

                        # Re-parse for each frame processed (bypass win2xcur internal inter-frame state pollution bug)
                        for frame_idx in range(len(cursor_temp.frames)):
                            cursor_fresh = open_blob(
                                cursor_data
                            )  # Re-parse to avoid inter-frame pollution
                            frame = cursor_fresh.frames[frame_idx]

                            # Get source size image
                            img = next(
                                (i for i in frame.images if i.nominal == original_size),
                                None,
                            )
                            if img is None and frame.images:
                                max_in_frame = max(i.nominal for i in frame.images)
                                img = next(
                                    (
                                        i
                                        for i in frame.images
                                        if i.nominal == max_in_frame
                                    ),
                                    frame.images[0],
                                )
                            if img is None:
                                size_frames.append(
                                    CursorFrame(images=[], delay=frame.delay)
                                )
                            else:
                                temp_frame = CursorFrame(
                                    images=[img], delay=frame.delay
                                )
                                scale_to_frames([temp_frame], scale=scale_ratio)
                                size_frames.append(temp_frame)

                        # Fix nominal value (apply_to_frames doesn't update it automatically)
                        for frame in size_frames:
                            for image in frame.images:
                                image.nominal = target_size

                        self.log(
                            _(
                                "  Scaled to generate {}x{} (from {}x{}, {} frames)"
                            ).format(
                                target_size,
                                target_size,
                                original_size,
                                original_size,
                                len(size_frames),
                            )
                        )

                    # If needed, add shadow (simulate Windows cursor shadow, parameters are relative proportions)
                    if add_shadow:
                        add_shadow_to_frames(
                            size_frames,
                            color="black",
                            radius=0.08,
                            sigma=0.04,
                            xoffset=0.02,
                            yoffset=0.02,
                        )

                    # Merge into merged_frames by frame (keep frame count = base_frame_count, not multiply by size count)
                    if not merged_frames:
                        # First size: directly establish skeleton
                        from win2xcur.cursor import CursorFrame

                        merged_frames = [
                            CursorFrame(images=list(fr.images), delay=fr.delay)
                            for fr in size_frames[:base_frame_count]
                        ]
                    else:
                        # Subsequent sizes: append images to corresponding frames
                        for idx in range(min(len(merged_frames), len(size_frames))):
                            merged_frames[idx].images.extend(size_frames[idx].images)

            # Check if any frames were successfully generated
            if not merged_frames or all(len(fr.images) == 0 for fr in merged_frames):
                self.log(_("✗ Failed to generate any sizes: {}").format(cursor_file))
                return False

            # Convert to X11 format
            x11_data = to_x11(merged_frames)

            # Write file
            with open(output_file, "wb") as f:
                f.write(x11_data)

            self.log(
                _("  ✓ Generated cursor file with {} sizes ({} frames)").format(
                    len(target_sizes), len(merged_frames)
                )
            )
            return True

        except Exception as e:
            self.log(_("✗ Conversion failed {}: {}").format(cursor_file, e))
            import traceback

            traceback.print_exc()
            return False

    def create_symlinks(self, cursors_dir: str) -> int:
        """
        Create symbolic links

        Args:
            cursors_dir: cursor directory path

        Returns:
            number of symbolic links created
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
                    pass  # Ignore link creation failure

        self.log(_("✓ Created {} symbolic links").format(created))
        return created

    def create_index_theme(self, output_dir: str, theme_name: str) -> bool:
        """
        Create index.theme file

        Args:
            output_dir: output directory
            theme_name: theme name

        Returns:
            whether creation succeeded
        """
        index_path = os.path.join(output_dir, "index.theme")
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"[Icon Theme]\n")
                f.write(f"Name={theme_name}\n")
                f.write(f"Comment=Converted from Windows cursor theme\n")
                f.write(f"Example=default\n")
            self.log(_("✓ Created index.theme"))
            return True
        except Exception as e:
            self.log(_("Failed to create index.theme: {}").format(e))
            return False
