"""Windows INF file parser module"""

import re
import gettext
from .constants import WIN_CURSOR_ORDER

_ = gettext.gettext


class INFParser:
    """Parse Windows INF cursor theme installation file"""

    def __init__(self, inf_path: str):
        self.inf_path = inf_path
        self.theme_name = ""
        self.cursor_files = {}

    def parse(self) -> bool:
        """Parse INF file"""
        try:
            # Read file content, try multiple encodings
            content = None
            for encoding in ["utf-8", "gbk", "gb2312", "utf-16", "latin1"]:
                try:
                    with open(self.inf_path, "r", encoding=encoding) as f:
                        content = f.read()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if content is None:
                return False

            # Convert to lowercase uniformly to avoid case sensitivity issues
            content = content.lower()

            # Parse using regular expressions
            strings_section = self._extract_section(content, "strings")
            addreg_sections = self._get_addreg_sections(content)
            theme_value, scheme_reg = self._extract_scheme_reg(content, addreg_sections)

            # Parse Strings section (if exists)
            string_vars = {}
            if strings_section:
                string_vars = self._parse_strings(strings_section)

            # Get theme name: check if using variables
            if theme_value:
                if '%' in theme_value:
                    # Using variable: lookup from Strings
                    var_match = re.search(r'%(\w+)%', theme_value)
                    if var_match:
                        var_name = var_match.group(1).lower()
                        if var_name in string_vars:
                            self.theme_name = string_vars[var_name]
                        else:
                            self.theme_name = _("Untitled Theme")
                    else:
                        self.theme_name = _("Untitled Theme")
                else:
                    self.theme_name = theme_value
            else:
                self.theme_name = _("Untitled Theme")

            # Parse cursor mapping in Scheme.Reg
            if scheme_reg:
                self._parse_cursor_mapping(scheme_reg, string_vars)

            return True

        except Exception as e:
            print(_("Error parsing INF file: {}").format(e))
            import traceback

            traceback.print_exc()
            return False

    def _extract_section(self, content: str, section_name: str):
        """Extract specified section content (section_name should be lowercase)"""
        pattern = rf"\[{section_name}\](.*?)(?=\n\[|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _get_addreg_sections(self, content: str) -> list[str]:
        """Parse AddReg specified section name list from [DefaultInstall].

        For example, AddReg = Scheme.Reg,Wreg returns ['scheme.reg', 'wreg'].
        """
        default_install = self._extract_section(content, "defaultinstall")
        if not default_install:
            return []

        for line in default_install.split("\n"):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            # Match AddReg = value or AddReg=value, value may contain commas
            m = re.match(r"addreg\s*=\s*(.+)", line, re.IGNORECASE)
            if m:
                value = m.group(1).strip()
                # Split by comma, strip whitespace, and convert to lowercase to match _extract_section
                return [s.strip().lower() for s in value.split(",") if s.strip()]
        return []

    def _extract_scheme_reg(self, content: str, addreg_sections: list[str]):
        """Find HKCU + Control Panel\\Cursors\\Schemes line from AddReg specified sections, extract theme name and cursor list.

        Returns: (theme_name_or_var, cursor_list)
        - theme_name_or_var: theme name (might be variable name or direct value)
        - cursor_list: cursor list string (might contain variables or direct filenames)
        """
        for section_name in addreg_sections:
            # Section name in INF usually has brackets, and case may vary, content has been converted to lowercase so use lowercase section_name
            pattern = rf"\[{re.escape(section_name)}\](.*?)(?=\n\[|\Z)"
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if not match:
                continue

            section = match.group(1).strip()
            hkcu_lines = [
                line.strip()
                for line in section.split("\n")
                if line.strip().lower().startswith("hkcu")
            ]

            for line in hkcu_lines:
                if "control panel" not in line.lower() or "cursors" not in line.lower() or "schemes" not in line.lower():
                    continue

                quoted_pattern = r'"([^"]*(?:""[^"]*)*)"'
                parts = re.findall(quoted_pattern, line)
                if len(parts) < 2:
                    continue

                theme_value = parts[1]
                cursor_list = parts[-1]
                return (theme_value, cursor_list)

        return (None, None)

    def _parse_strings(self, strings_content: str):
        """Parse variable definitions in Strings section (already converted to lowercase)"""
        result = {}
        for line in strings_content.split("\n"):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            # Match key = "value" or key = value
            match = re.match(r'(\w+)\s*=\s*"?([^"]+)"?', line)
            if match:
                key, value = match.groups()
                result[key.lower()] = value.strip('"').strip()
        return result

    def _parse_cursor_mapping(self, scheme_reg: str, string_vars):
        # Split by comma
        parts = scheme_reg.split(',')

        cursor_index = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue

            if cursor_index >= len(WIN_CURSOR_ORDER):
                break

            # Split by backslash, take last element
            segments = part.split('\\')
            last_segment = segments[-1].strip()

            if not last_segment:
                continue

            win_cursor_type = WIN_CURSOR_ORDER[cursor_index]

            # Check if it's a variable
            if '%' in last_segment:
                # Extract variable name
                var_match = re.search(r'%(\w+)%', last_segment)
                if var_match:
                    var_name = var_match.group(1).lower()
                    if var_name in string_vars:
                        self.cursor_files[win_cursor_type] = string_vars[var_name]
                        cursor_index += 1
            else:
                # Direct filename
                if last_segment.lower().endswith(('.cur', '.ani')):
                    self.cursor_files[win_cursor_type] = last_segment
                    cursor_index += 1
