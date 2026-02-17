"""Data model module"""

import gettext
from gi.repository import GObject

_ = gettext.gettext


class ThemeNameModel(GObject.Object):
    """Theme name GObject model, bidirectionally synchronized with Entry through bind_property."""

    theme_name = GObject.Property(type=str, default="", nick=_("Theme Name"))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
