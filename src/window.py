import os
import zipfile
import tempfile
import shutil
import re
import threading
import queue
import gettext

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GObject

from .constants import WIN_TO_XCURSOR
from .models import ThemeNameModel
from .inf_parser import INFParser
from .converter import CursorConverter
from .cursor_preview import CursorPreviewDialog

_ = gettext.gettext


class Win2xcurGuiWindow(Adw.ApplicationWindow):
    """Main window"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title(_("Windows Cursor Theme Converter"))
        self.set_default_size(800, 600)

        # Create main layout
        self.setup_ui()

        # State variables
        self.zip_path = None
        self.temp_dir = None
        self.inf_parser = None
        self.inf_dir = None  # INF file directory
        self.output_dir = None  # Output directory

        # Initialize converter
        self.converter = CursorConverter(log_callback=self.log)

    def setup_ui(self):
        """Setup user interface"""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)

        # Use Stack to manage multiple pages
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        main_box.append(self.stack)

        # ===== Page 1: Welcome page (StatusPage + drag-drop) =====
        welcome_page = self.create_welcome_page()
        self.stack.add_named(welcome_page, "welcome")

        # ===== Page 2: Config page =====
        config_page = self.create_config_page()
        self.stack.add_named(config_page, "config")

        # Show welcome page by default
        self.stack.set_visible_child_name("welcome")

    def create_welcome_page(self):
        """Create welcome page"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_vexpand(True)

        # StatusPage
        status = Adw.StatusPage()
        status.set_icon_name("folder-download-symbolic")
        status.set_title(_("Windows Cursor Theme Converter"))
        status.set_description(_("Drag in a ZIP file or click the button to select a file\nSupports .cur and .ani formats"))
        page.append(status)

        # Button container
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(20)
        page.append(button_box)

        # Select file button
        select_btn = Gtk.Button(label=_("Select ZIP File"))
        select_btn.add_css_class("pill")
        select_btn.add_css_class("suggested-action")
        select_btn.connect("clicked", self.on_select_file)
        button_box.append(select_btn)

        # Setup drop target
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_file_dropped)
        page.add_controller(drop_target)

        return page

    def create_config_page(self):
        """Create config page"""
        # Scroll container
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        # Content area
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)
        scroll.set_child(content)

        # File info
        file_group = Adw.PreferencesGroup()
        file_group.set_title(_("Current File"))
        content.append(file_group)

        self.file_info_row = Adw.ActionRow()
        self.file_info_row.set_title(_("No file selected"))

        change_btn = Gtk.Button(label=_("Change File"))
        change_btn.set_valign(Gtk.Align.CENTER)
        change_btn.connect("clicked", self.on_select_file)
        self.file_info_row.add_suffix(change_btn)
        file_group.add(self.file_info_row)

        # Info display area
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Theme Information"))
        content.append(info_group)

        theme_name_row = Adw.ActionRow()
        theme_name_row.set_title(_("Theme Name"))
        self.theme_name_entry = Gtk.Entry()
        self.theme_name_entry.set_placeholder_text(_("Untitled Theme"))
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
        self.cursor_count_row.set_title(_("Cursor Count"))
        self.cursor_count_row.set_subtitle("--")
        info_group.add(self.cursor_count_row)

        # Options area
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("Conversion Options"))
        content.append(options_group)

        shadow_row = Adw.ActionRow()
        shadow_row.set_title(_("Add Shadow Effect"))
        shadow_row.set_subtitle(_("Simulate Windows cursor shadow"))
        self.shadow_switch = Gtk.Switch()
        self.shadow_switch.set_valign(Gtk.Align.CENTER)
        shadow_row.add_suffix(self.shadow_switch)
        shadow_row.set_activatable_widget(self.shadow_switch)
        options_group.add(shadow_row)

        symlink_row = Adw.ActionRow()
        symlink_row.set_title(_("Create Symbolic Links"))
        symlink_row.set_subtitle(_("Create symbolic links for common cursor names"))
        self.symlink_switch = Gtk.Switch()
        self.symlink_switch.set_active(True)
        self.symlink_switch.set_valign(Gtk.Align.CENTER)
        symlink_row.add_suffix(self.symlink_switch)
        symlink_row.set_activatable_widget(self.symlink_switch)
        options_group.add(symlink_row)

        # Multi-size options
        size_row = Adw.ExpanderRow()
        size_row.set_title(_("Generate Multi-Size Cursors"))
        size_row.set_subtitle(_("Select sizes to generate (multiple selection allowed)"))
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

        # Output directory selection
        output_row = Adw.ActionRow()
        output_row.set_title(_("Output Directory"))
        self.output_label = Gtk.Label(label=_("/tmp/<theme_name>"))
        self.output_label.add_css_class("dim-label")
        output_row.add_suffix(self.output_label)

        output_btn = Gtk.Button(label=_("Select Directory"))
        output_btn.connect("clicked", self.on_select_output)
        output_row.add_suffix(output_btn)
        options_group.add(output_row)

        # Log area (at the top)
        log_group = Adw.PreferencesGroup()
        log_group.set_title(_("Conversion Log"))
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

        self.convert_btn = Gtk.Button(label=_("Start Conversion"))
        self.convert_btn.add_css_class("suggested-action")
        self.convert_btn.add_css_class("pill")
        self.convert_btn.set_sensitive(False)
        self.convert_btn.connect("clicked", self.on_convert)
        self.button_box.append(self.convert_btn)

        self.preview_btn = Gtk.Button(label=_("Preview Cursors"))
        self.preview_btn.add_css_class("pill")
        self.preview_btn.set_sensitive(False)
        self.preview_btn.connect("clicked", self.on_preview_cursors)
        self.button_box.append(self.preview_btn)

        self.apply_btn = Gtk.Button(label=_("Install Theme"))
        self.apply_btn.add_css_class("pill")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", self.on_install_theme)
        self.button_box.append(self.apply_btn)

        return scroll

    def log(self, message: str):
        """Thread-safe: put message in queue, written by main thread to TextView."""
        self._log_queue.put_nowait(message)
        GLib.idle_add(self._flush_log_queue)

    def _flush_log_queue(self):
        """Main thread only: get all pending log messages from queue, insert at once and scroll to bottom."""
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
        """Handle dropped file"""
        if isinstance(value, Gio.File):
            file_path = value.get_path()
            if file_path and file_path.lower().endswith('.zip'):
                self.zip_path = file_path
                self.file_info_row.set_title(os.path.basename(file_path))
                self.log(_("Selected file: {}").format(self.zip_path))

                # Reset output directory after changing file, so output path follows theme name
                self.output_dir = None

                # Switch to config page
                self.stack.set_visible_child_name("config")

                # Parse ZIP file
                self.parse_zip()
                return True
        return False

    def on_select_file(self, button):
        """Select ZIP file"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Cursor Theme Archive"))

        # Set file filter
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name(_("ZIP Archive"))
        zip_filter.add_pattern("*.zip")

        all_filter = Gtk.FileFilter()
        all_filter.set_name(_("All Files"))
        all_filter.add_pattern("*")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zip_filter)
        filters.append(all_filter)
        dialog.set_filters(filters)

        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        """File selection completed"""
        try:
            file = dialog.open_finish(result)
            if file:
                self.zip_path = file.get_path()
                self.file_info_row.set_title(os.path.basename(self.zip_path))
                self.log(_("Selected file: {}").format(self.zip_path))

                # Reset output directory after changing file, so output path follows theme name
                self.output_dir = None

                # Switch to config page
                self.stack.set_visible_child_name("config")

                # Parse ZIP file
                self.parse_zip()
        except GLib.Error as e:
            if e.code != 2:  # 2 = dismissed
                self.log(_("Error: {}").format(e.message))

    def detect_zip_encoding(self, zip_path):
        """Detect ZIP file encoding by reading raw bytes from local file headers"""
        encoding_candidates = ["utf-8", "gbk", "big5", "shift_jis"]
        
        with open(zip_path, 'rb') as f:
            # Scan for local file headers (0x04034b50)
            while True:
                chunk = f.read(4)
                if len(chunk) < 4:
                    break
                
                if chunk == b'\x50\x4b\x03\x04':  # Local file header signature
                    # Read local file header
                    f.read(2)  # version needed
                    flag_bits = int.from_bytes(f.read(2), 'little')
                    
                    # Check UTF-8 flag (bit 11)
                    if flag_bits & 0x800:
                        return "utf-8"
                    
                    f.read(16)  # Skip: compression, mod time, mod date, crc32, compressed size, uncompressed size
                    filename_len = int.from_bytes(f.read(2), 'little')
                    extra_len = int.from_bytes(f.read(2), 'little')
                    
                    # Read raw filename bytes
                    filename_bytes = f.read(filename_len)
                    f.read(extra_len)  # Skip extra field
                    
                    # Skip pure ASCII filenames (can't determine encoding from them)
                    try:
                        filename_bytes.decode('ascii')
                        continue
                    except UnicodeDecodeError:
                        pass
                    
                    # Try different encodings on raw bytes
                    for encoding in encoding_candidates:
                        try:
                            filename_bytes.decode(encoding)
                            return encoding
                        except (UnicodeDecodeError, LookupError):
                            continue
                    
                    # If we found a non-ASCII filename but can't decode it, return gbk as fallback
                    return "gbk"
                elif chunk == b'\x50\x4b\x01\x02':  # Central directory header
                    # Reached central directory, stop scanning
                    break
                else:
                    # Not a header, move back 3 bytes and continue
                    f.seek(-3, 1)
        
        return "utf-8"

    def parse_zip(self):
        """Parse ZIP file"""
        try:
            # Clean up old temporary directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)

            # Create temporary directory
            self.temp_dir = tempfile.mkdtemp(prefix="win2xcur_")

            if not self.zip_path:
                self.log(_("Error: No file selected"))
                return

            # Detect ZIP encoding
            encoding = self.detect_zip_encoding(self.zip_path)
            self.log(_("Detected ZIP encoding: {}").format(encoding.upper()))

            # Extract ZIP
            self.log(_("Extracting files..."))
            with zipfile.ZipFile(self.zip_path, "r") as zip_ref:
                if encoding != "utf-8":
                    # Need to decode filenames using detected encoding
                    # Build filename mapping by reading raw bytes from local file headers
                    filename_map = {}
                    with open(self.zip_path, 'rb') as f:
                        for member in zip_ref.namelist():
                            # Find this file's local header
                            info = zip_ref.getinfo(member)
                            f.seek(info.header_offset)
                            
                            # Verify local file header signature
                            if f.read(4) != b'\x50\x4b\x03\x04':
                                filename_map[member] = member
                                continue
                            
                            f.read(22)  # Skip to filename length
                            filename_len = int.from_bytes(f.read(2), 'little')
                            f.read(2)  # Skip extra field length
                            
                            # Read raw filename bytes
                            filename_bytes = f.read(filename_len)
                            
                            try:
                                correct_name = filename_bytes.decode(encoding)
                                filename_map[member] = correct_name
                            except Exception:
                                filename_map[member] = member
                    
                    # Extract with corrected filenames
                    for member in zip_ref.namelist():
                        member_name = filename_map.get(member, member)
                        
                        source = zip_ref.open(member)
                        target_path = os.path.join(self.temp_dir, member_name)
                        
                        if member_name.endswith('/'):
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            parent_dir = os.path.dirname(target_path)
                            if parent_dir:
                                os.makedirs(parent_dir, exist_ok=True)
                            with open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                else:
                    # UTF-8 encoding, extract directly
                    zip_ref.extractall(self.temp_dir)

            # Search for INF file
            inf_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith(".inf"):
                        inf_files.append(os.path.join(root, file))

            if not inf_files:
                self.log(_("Error: No INF file found"))
                return

            # Use the first INF file
            inf_path = inf_files[0]
            self.inf_dir = os.path.dirname(inf_path)  # Save INF file directory
            self.log(_("Found INF file: {}").format(os.path.basename(inf_path)))

            # Parse INF
            self.inf_parser = INFParser(inf_path)
            if self.inf_parser.parse():
                self.cursor_count_row.set_subtitle(
                    str(len(self.inf_parser.cursor_files))
                )
                self.log(_("Theme name: {}").format(self.inf_parser.theme_name))
                self.log(_("Found {} cursors").format(len(self.inf_parser.cursor_files)))
                # Theme name: GObject property, bound to Entry, just set initial value here
                self.theme_name_model.set_property("theme-name", self.inf_parser.theme_name)

                # Show default path when output directory is not manually selected
                if not self.output_dir:
                    self.output_label.set_text(f"/tmp/{self.get_theme_name_for_path()}")

                # Show cursor mapping
                for win_type, filename in self.inf_parser.cursor_files.items():
                    xcursor_name = WIN_TO_XCURSOR.get(win_type, win_type)
                    self.log(f"  {win_type} -> {xcursor_name}: {filename}")

                self.convert_btn.set_sensitive(True)
            else:
                self.log(_("Error: Cannot parse INF file"))

        except Exception as e:
            self.log(_("Parse error: {}").format(e))
            import traceback
            traceback.print_exc()

    def _on_theme_name_notify(self, obj, pspec):
        """Update default output path display when theme name property changes"""
        if not self.output_dir and self.inf_parser:
            name = self.get_theme_name_for_path() or _("Untitled Theme")
            self.output_label.set_text(f"/tmp/{name}")

    def get_theme_name(self):
        """Current theme name: from GObject property bound to Entry."""
        name = (self.theme_name_model.get_property("theme-name") or "").strip()
        return name if name else _("Untitled Theme")

    def get_theme_name_for_path(self):
        """Get theme name for path (remove illegal characters)"""
        name = self.get_theme_name()
        return re.sub(r'[/\\:*?"<>|]', '_', name) or _("Untitled Theme")

    def on_select_output(self, button):
        """Select output directory"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Output Directory"))
        dialog.select_folder(self, None, self.on_output_selected)

    def on_output_selected(self, dialog, result):
        """Output directory selection completed"""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.output_dir = folder.get_path()
                self.output_label.set_text(self.output_dir)
                self.log(_("Output directory: {}").format(self.output_dir))
        except GLib.Error as e:
            if e.code != 2:
                self.log(_("Error: {}").format(e.message))

    def on_convert(self, button):
        """Start conversion"""
        if not self.inf_parser:
            self.log(_("Error: No theme file selected"))
            return

        # Determine output directory (use /tmp by default)
        if not self.output_dir:
            self.output_dir = os.path.join("/tmp", self.get_theme_name_for_path())

        cursors_dir = os.path.join(self.output_dir, "cursors")
        os.makedirs(cursors_dir, exist_ok=True)

        self.log(_("\nStarting conversion to: {}").format(cursors_dir))
        self.button_box.set_visible(False)
        self.progress_clamp.set_visible(True)
        self.progress_bar.set_fraction(0.0)
        self.progress_label.set_text(_("Preparing conversion..."))

        # Check if win2xcur is available
        try:
            from win2xcur.parser import open_blob
            from win2xcur.writer import to_x11

            self.log(_("✓ Found win2xcur module"))
        except ImportError:
            self.log(_("✗ win2xcur module not found"))
            self.log(_("Please install: pip install win2xcur"))
            self.progress_clamp.set_visible(False)
            self.button_box.set_visible(True)
            self.convert_btn.set_sensitive(True)
            return

        # Execute conversion in background thread to avoid blocking UI
        def run():
            self._do_conversion_worker(cursors_dir)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _update_ui_progress(self, fraction: float, text: str):
        """Update progress bar and label in main thread (called by GLib.idle_add only)"""
        self.progress_bar.set_fraction(fraction)
        self.progress_label.set_text(text)

    def _do_conversion_worker(self, cursors_dir):
        """Actual conversion logic executed in background thread"""
        try:
            # Get user-selected target sizes
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
                self.log(_("✗ Please select at least one target size"))
                GLib.idle_add(self._on_conversion_error)
                return

            self.log(_("Target sizes: {}").format(', '.join(str(s) for s in target_sizes)))

            total = len(self.inf_parser.cursor_files)
            converted = 0
            add_shadow = self.shadow_switch.get_active()

            for win_type, filename in self.inf_parser.cursor_files.items():
                xcursor_name = WIN_TO_XCURSOR.get(win_type)
                if not xcursor_name:
                    self.log(_("Skipping unmapped type: {}").format(win_type))
                    continue

                output_file = os.path.join(cursors_dir, xcursor_name)

                # Update progress to main thread
                frac = (converted + 1) / total
                GLib.idle_add(
                    lambda f=frac, cn=converted+1, tot=total, fn=filename:
                    self._update_ui_progress(f, _("Converting {}/{}: {}").format(cn, tot, fn))
                )
                self.log(_("Converting: {} -> {}").format(filename, xcursor_name))

                # Use converter for conversion
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
                        self._update_ui_progress(c / t, _("Converting {}/{}").format(c, t))
                    )

            # Create symbolic links
            if self.symlink_switch.get_active():
                GLib.idle_add(
                    lambda c=converted, t=total:
                    self._update_ui_progress(c / t if t else 1.0, _("Creating symbolic links..."))
                )
                self.log(_("\nCreating symbolic links..."))
                self.converter.create_symlinks(cursors_dir)

            # Create index.theme
            GLib.idle_add(
                lambda: self._update_ui_progress(1.0, _("Creating theme config..."))
            )
            self.converter.create_index_theme(self.output_dir, self.get_theme_name())

            self.log(_("\n✓ Conversion complete! Successfully converted {}/{} cursors").format(converted, total))
            self.log(_("Theme location: {}").format(self.output_dir))
            self.log(_("\nConversion complete! Click [Install Theme] button to install to system"))

            GLib.idle_add(self._on_conversion_done)

        except Exception as e:
            self.log(_("\n✗ Error during conversion: {}").format(e))
            import traceback
            traceback.print_exc()
            GLib.idle_add(self._on_conversion_error)

    def _on_conversion_done(self):
        """Conversion successful, restore UI in main thread"""
        self.progress_clamp.set_visible(False)
        self.button_box.set_visible(True)
        self.convert_btn.set_sensitive(True)
        self.preview_btn.set_sensitive(True)
        self.apply_btn.set_sensitive(True)

    def _on_conversion_error(self):
        """Conversion error, restore UI in main thread"""
        self.progress_clamp.set_visible(False)
        self.button_box.set_visible(True)
        self.convert_btn.set_sensitive(True)
        self.preview_btn.set_sensitive(False)
        self.apply_btn.set_sensitive(False)

    def on_preview_cursors(self, button):
        """Open cursor preview dialog (reference xcursor-viewer, animated cursors play continuously)"""
        if not self.output_dir:
            self.log(_("Error: Please complete conversion first"))
            return
        cursors_dir = os.path.join(self.output_dir, "cursors")
        if not os.path.isdir(cursors_dir):
            self.log(_("Error: cursors directory not found"))
            return
        dialog = CursorPreviewDialog(cursors_dir=cursors_dir)
        dialog.present(self)

    def on_install_theme(self, button):
        """Install theme to user icon directory (only copy files, don't modify system/desktop theme settings)"""
        if not self.inf_parser or not self.output_dir:
            self.log(_("Error: Please convert theme first"))
            return

        self.apply_btn.set_sensitive(False)
        self.log(_("\nStarting theme installation to system..."))

        data_home = os.environ.get(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local/share")
        )

        icons_dir = os.path.join(data_home, "icons")

        os.makedirs(icons_dir, exist_ok=True)

        target_dir = os.path.join(icons_dir, self.get_theme_name_for_path())

        try:
            # If target already exists, delete it first
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)

            # Copy theme files
            self.log(_("Copying theme to: {}").format(target_dir))
            shutil.copytree(self.output_dir, target_dir, symlinks=True)
            self.log(_("✓ Theme installed, please manually select this cursor theme in system settings"))

            self.apply_btn.set_sensitive(True)

        except Exception as e:
            self.log(_("✗ Installation failed: {}").format(e))
            import traceback
            traceback.print_exc()
            self.apply_btn.set_sensitive(True)

    def do_close_request(self):
        """Cleanup when window closes"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
        return False
