"""Sun Valley ttk 主题封装"""

import sv_ttk

# 当前主题（"light" 或 "dark"）
_current = "light"


def set_current(name):
    global _current
    _current = name if name in ("light", "dark") else "light"


def get_current():
    return _current


def apply(root):
    """应用主题到给定 Tk 根窗口（必须在 Tk() 创建之后调用）"""
    try:
        sv_ttk.set_theme(_current, root)
    except TypeError:
        # 老版本 sv_ttk 不接受 root 参数
        sv_ttk.set_theme(_current)


# 各主题下 Listbox / Text 等非 ttk 控件的配色
PALETTE = {
    "light": {
        "bg": "#fafafa",
        "fg": "#1f1f1f",
        "select_bg": "#0078d4",
        "select_fg": "#ffffff",
        "border": "#d0d0d0",
    },
    "dark": {
        "bg": "#2b2b2b",
        "fg": "#e0e0e0",
        "select_bg": "#0078d4",
        "select_fg": "#ffffff",
        "border": "#3c3c3c",
    },
}


def palette():
    return PALETTE[_current]
