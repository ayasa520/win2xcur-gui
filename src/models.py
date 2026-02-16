"""数据模型模块"""

from gi.repository import GObject


class ThemeNameModel(GObject.Object):
    """主题名称的 GObject 模型，与 Entry 通过 bind_property 双向同步。"""

    theme_name = GObject.Property(type=str, default="", nick="主题名称")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
