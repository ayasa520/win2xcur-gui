"""Cursor conversion module"""

import os
import gettext
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
        Convert single cursor file

        Args:
            cursor_file: cursor file path or filename
            output_file: output file path
            target_sizes: target size list
            add_shadow: whether to add shadow
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
            self.log(_("  Original file sizes: {}").format(','.join(str(x) for x in sorted(original_sizes))))

            # Generate frames for each target size (finally merge by frame index, not concatenate)
            base_frame_count = len(cursor.frames)
            merged_frames = []  # Final output: merge multiple sizes by frame
            
            for target_size in target_sizes:
                # Re-parse original data each time (avoid deepcopy issues)
                cursor_temp = open_blob(cursor_data)

                if target_size in original_sizes:
                    # Original file already has this size, directly extract frames of corresponding size
                    size_frames = []
                    for frame in cursor_temp.frames:
                        # Only keep images of target size
                        matching_images = [img for img in frame.images if img.nominal == target_size]
                        if matching_images:
                            # Create new frame, only include images of this size
                            from win2xcur.cursor import CursorFrame
                            new_frame = CursorFrame(images=matching_images, delay=frame.delay)
                            size_frames.append(new_frame)
                    self.log(_("  Using original {}x{} ({} frames)").format(target_size, target_size, len(size_frames)))
                else:
                    # Need to scale to generate: only take one image from source size (maximum size), avoid scaling multiple sizes together
                    if not original_sizes:
                        self.log(_("  ✗ Cannot generate {}x{}: original file has no valid sizes").format(target_size, target_size))
                        continue

                    from win2xcur.cursor import CursorFrame
                    original_size = max(original_sizes)  # Use maximum original size as source
                    size_frames = []
                    scale_ratio = target_size / original_size
                    
                    # Re-parse for each frame processed (bypass win2xcur internal inter-frame state pollution bug)
                    for frame_idx in range(len(cursor_temp.frames)):
                        cursor_fresh = open_blob(cursor_data)  # Re-parse to avoid inter-frame pollution
                        frame = cursor_fresh.frames[frame_idx]
                        
                        # Get source size image
                        img = next((i for i in frame.images if i.nominal == original_size), None)
                        if img is None and frame.images:
                            max_in_frame = max(i.nominal for i in frame.images)
                            img = next((i for i in frame.images if i.nominal == max_in_frame), frame.images[0])
                        if img is None:
                            size_frames.append(CursorFrame(images=[], delay=frame.delay))
                        else:
                            temp_frame = CursorFrame(images=[img], delay=frame.delay)
                            scale_to_frames([temp_frame], scale=scale_ratio)
                            size_frames.append(temp_frame)

                    # Fix nominal value (apply_to_frames doesn't update it automatically)
                    for frame in size_frames:
                        for image in frame.images:
                            image.nominal = target_size

                    self.log(_("  Scaled to generate {}x{} (from {}x{}, {} frames)").format(target_size, target_size, original_size, original_size, len(size_frames)))

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

            self.log(_("  ✓ Generated cursor file with {} sizes ({} frames)").format(len(target_sizes), len(merged_frames)))
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
