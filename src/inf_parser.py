"""Windows INF 文件解析模块"""

import re
from .constants import WIN_CURSOR_ORDER


class INFParser:
    """解析 Windows INF 光标主题安装文件"""

    def __init__(self, inf_path: str):
        self.inf_path = inf_path
        self.theme_name = ""
        self.cursor_files = {}

    def parse(self) -> bool:
        """解析 INF 文件"""
        try:
            # 读取文件内容，尝试多种编码
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

            # 统一转换为小写，避免大小写问题
            content = content.lower()

            # 使用正则表达式解析
            strings_section = self._extract_section(content, "strings")
            addreg_sections = self._get_addreg_sections(content)
            theme_value, scheme_reg = self._extract_scheme_reg(content, addreg_sections)

            # 解析 Strings 段（如果存在）
            string_vars = {}
            if strings_section:
                string_vars = self._parse_strings(strings_section)

            # 获取主题名称：检查是否使用变量
            if theme_value:
                if '%' in theme_value:
                    # 使用变量：从 Strings 查找
                    var_match = re.search(r'%(\w+)%', theme_value)
                    if var_match:
                        var_name = var_match.group(1).lower()
                        if var_name in string_vars:
                            self.theme_name = string_vars[var_name]
                        else:
                            self.theme_name = "未命名主题"
                    else:
                        self.theme_name = "未命名主题"
                else:
                    self.theme_name = theme_value
            else:
                self.theme_name = "未命名主题"

            # 解析 Scheme.Reg 中的光标映射
            if scheme_reg:
                self._parse_cursor_mapping(scheme_reg, string_vars)

            return True

        except Exception as e:
            print(f"解析 INF 文件错误: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _extract_section(self, content: str, section_name: str):
        """提取指定段落的内容（section_name 应为小写）"""
        pattern = rf"\[{section_name}\](.*?)(?=\n\[|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _get_addreg_sections(self, content: str) -> list[str]:
        """从 [DefaultInstall] 中解析 AddReg 指定的段名列表。

        例如 AddReg = Scheme.Reg,Wreg 返回 ['scheme.reg', 'wreg']。
        """
        default_install = self._extract_section(content, "defaultinstall")
        if not default_install:
            return []

        for line in default_install.split("\n"):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            # 匹配 AddReg = value 或 AddReg=value，value 可能含逗号
            m = re.match(r"addreg\s*=\s*(.+)", line, re.IGNORECASE)
            if m:
                value = m.group(1).strip()
                # 按逗号分隔，去掉空白，并统一为小写以匹配 _extract_section
                return [s.strip().lower() for s in value.split(",") if s.strip()]
        return []

    def _extract_scheme_reg(self, content: str, addreg_sections: list[str]):
        """从 AddReg 指定的段落中查找 HKCU + Control Panel\\Cursors\\Schemes 行，提取主题名和光标列表。

        返回: (theme_name_or_var, cursor_list)
        - theme_name_or_var: 主题名称（可能是变量名或直接值）
        - cursor_list: 光标列表字符串（可能包含变量或直接文件名）
        """
        for section_name in addreg_sections:
            # 段名在 INF 里通常带方括号，且大小写可能任意，content 已转小写故用 section_name 小写
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
        """解析 Strings 段落中的变量定义（已转为小写）"""
        result = {}
        for line in strings_content.split("\n"):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            # 匹配 key = "value" 或 key = value
            match = re.match(r'(\w+)\s*=\s*"?([^"]+)"?', line)
            if match:
                key, value = match.groups()
                result[key.lower()] = value.strip('"').strip()
        return result

    def _parse_cursor_mapping(self, scheme_reg: str, string_vars):
        # 按逗号分隔
        parts = scheme_reg.split(',')

        cursor_index = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue

            if cursor_index >= len(WIN_CURSOR_ORDER):
                break

            # 按反斜杠分隔，取最后一个元素
            segments = part.split('\\')
            last_segment = segments[-1].strip()

            if not last_segment:
                continue

            win_cursor_type = WIN_CURSOR_ORDER[cursor_index]

            # 检查是否是变量
            if '%' in last_segment:
                # 提取变量名
                var_match = re.search(r'%(\w+)%', last_segment)
                if var_match:
                    var_name = var_match.group(1).lower()
                    if var_name in string_vars:
                        self.cursor_files[win_cursor_type] = string_vars[var_name]
                        cursor_index += 1
            else:
                # 直接的文件名
                if last_segment.lower().endswith(('.cur', '.ani')):
                    self.cursor_files[win_cursor_type] = last_segment
                    cursor_index += 1
