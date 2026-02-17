"""Constant definition module"""

# Fixed mapping from Windows registry key names to xcursor names
# Order in HKCU line of Scheme.Reg is fixed, corresponding to these Windows cursor types by position
WIN_CURSOR_ORDER = [
    "arrow",  # 0: Normal Select
    "help",  # 1: Help Select
    "appstarting",  # 2: Working in Background
    "wait",  # 3: Busy
    "crosshair",  # 4: Precision Select
    "ibeam",  # 5: Text Select
    "pen",  # 6: Handwriting
    "no",  # 7: Unavailable
    "ns",  # 8: Vertical Resize
    "we",  # 9: Horizontal Resize
    "nwse",  # 10: Diagonal Resize 1
    "nese",  # 11: Diagonal Resize 2
    "move",  # 12: Move
    "uparrow",  # 13: Alternate Select
    "hand",  # 14: Link Select
    # "pin",  # 15: Pin
    # "person",  # 16: Person
]

# Windows cursor type to xcursor name mapping
WIN_TO_XCURSOR = {
    "arrow": "default",
    "help": "help",
    "appstarting": "progress",
    "wait": "wait",
    "crosshair": "crosshair",
    "ibeam": "xterm",
    "pen": "pencil",
    "no": "circle",
    "ns": "size_ver",
    "we": "size_hor",
    "nwse": "size_fdiag",
    "nese": "size_bdiag",
    "move": "fleur",
    "uparrow": "uparrow",
    "hand": "hand",
    # pin 和 person  没有对应的
}

# 符号链接映射
SYMLINK_MAP = {
    "default": ["arrow", "left_ptr"],
    "help": [
        "5c6cd98b3f3ebcb1f9c7f1c204630408",
        "d9ce0ab605698f320427677b458ad60b",
        "question_arrow",
        "whats_this",
    ],
    "progress": [
        "00000000000000020006000e7e9ffc3f",
        "08e8e1c95fe2fc01f976f1e063a24ccd",
        "3ecb610c1bf2410f44200f48c40d3599",
        "half-busy",
        "left_ptr_watch",
    ],
    "wait": ["watch"],
    "crosshair": ["cross"],
    "xterm": ["ibeam", "text"],
    "circle": ["03b6e0fcb3499374a867c041f52298f0"],
    "size_ver": [
        "00008160000006810000408080010102",
        "bottom_side",
        "n-resize",
        "row-resize",
        "sb_v_double_arrow",
        "split_v",
        "s-resize",
        "top_side",
        "ns-resize",
    ],
    "size_hor": [
        "col-resize",
        "e-resize",
        "h_double_arrow",
        "left_side",
        "right_side",
        "sb_h_double_arrow",
        "split_h",
        "w-resize",
        "we-resize",
    ],
    "size_bdiag": [
        "bottom_left_corner",
        "ll_angle",
        "sw-resize",
        "top_right_corner",
        "ur_angle",
    ],
    "size_fdiag": [
        "bottom_right_corner",
        "lr_angle",
        "se-resize",
        "top_left_corner",
        "ul_angle",
        "nwse-resize",
    ],
    "fleur": ["all-scroll", "size_all"],
    "hand": ["hand2", "pointer"],
    "hand2": ["closedhand"],
    "top_right_corner": ["ne-resize"],
    "top_left_corner": ["nw-resize"],
    "pointer": ["9d800788f1b08800ae810202380a0822", "e29285e634086352946a0e7090d73106"],
}
