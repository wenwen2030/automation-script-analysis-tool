"""日志语法高亮：按规则给 Text 控件的内容标 tag

各 tag 已在 dialog.py 中通过 tag_configure 配置好颜色。
"""

import re

# 高亮规则：(正则, tag名)
# 顺序很重要：先匹配的优先（先标记后面的就会跳过已标记的位置）
RULES = [
    # 时间戳: 09:32:21
    (re.compile(r"\b\d{2}:\d{2}:\d{2}\b"), "ts"),
    # IP 地址 (v4)
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d+)?\b"), "ip"),
    # MAC 地址
    (re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b"), "mac"),
    # Pass / OK / success
    (re.compile(r"\b(?:PASS|pass|Success|success|OK|ok|connected|Enabled)\b"), "ok"),
    # Fail / Error / unsupported / disabled
    (re.compile(r"\b(?:FAIL|Fail|fail|ERROR|Error|error|errExe|errScript\w*|Failed|failed|unsupported|Disabled|disabled)\b"), "err"),
    # 警告
    (re.compile(r"\b(?:WARN|Warning|warning|TIMEOUT|timeout|stall)\b"), "warn"),
    # 数字（带逗号或点的）
    (re.compile(r"\b\d{4,}\b"), "num"),
    # PicOS 提示符相关
    (re.compile(r"admin@\w+[#>$]"), "prompt"),
    # 关键词：Step/Proc/Logging/Entering
    (re.compile(r"#Proc\b|::Step\s*[\d.]+|Entering|Logging"), "kw"),
    # 引号字符串
    (re.compile(r'"[^"\n]{1,120}"'), "str"),
]


def configure_tags(text_widget):
    """在 Text 控件上配置好所有高亮 tag"""
    text_widget.tag_configure("ts",     foreground="#ce9178")  # 时间戳：橙红
    text_widget.tag_configure("ip",     foreground="#dcdcaa")  # IP：黄
    text_widget.tag_configure("mac",    foreground="#dcdcaa")  # MAC：黄
    text_widget.tag_configure("ok",     foreground="#6a9955")  # 通过：绿
    text_widget.tag_configure("err",    foreground="#f44747")  # 错误：红
    text_widget.tag_configure("warn",   foreground="#ffb86c")  # 警告：橙
    text_widget.tag_configure("num",    foreground="#b5cea8")  # 数字：浅绿
    text_widget.tag_configure("prompt", foreground="#9cdcfe")  # 提示符：浅蓝
    text_widget.tag_configure("kw",     foreground="#c586c0")  # 关键字：紫
    text_widget.tag_configure("str",    foreground="#ce9178")  # 字符串：橙


def highlight_text(text_widget, start="1.0", end=None):
    """对 Text 控件指定范围内的文本应用高亮规则"""
    if end is None:
        end = "end-1c"
    # tag_add 在 DISABLED 状态下也能工作，但保险起见切到 NORMAL
    prev_state = str(text_widget.cget("state"))
    if prev_state == "disabled":
        text_widget.config(state="normal")
    try:
        content = text_widget.get(start, end)
        for pattern, tag in RULES:
            for m in pattern.finditer(content):
                s = f"{start}+{m.start()}c"
                e = f"{start}+{m.end()}c"
                text_widget.tag_add(tag, s, e)
    finally:
        if prev_state == "disabled":
            text_widget.config(state="disabled")
