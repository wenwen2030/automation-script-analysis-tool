"""脚本源码查看器：根据脚本名在本地目录搜索对应 tcl 文件并显示"""

import os
import re
import threading
import tkinter as tk
import tkinter.ttk as ttk

from .search_bar import SearchBar

# 默认搜索根目录（可在 config 中覆盖）
DEFAULT_SCRIPT_DIR = r"Z:\automation\suite\xorplus"


def find_script_file(script_name, search_dir=None):
    """在 search_dir 下递归搜索包含 script_name 的 .tcl 文件
    
    搜索策略：
    1. 精确匹配：文件名 == pica8{script_name}.tcl 或 {script_name}.tcl
    2. 模糊匹配：文件名包含 script_name（去掉 _XX_XX 后缀后的 feature 名）
    
    返回找到的文件完整路径，或 None
    """
    if search_dir is None:
        search_dir = DEFAULT_SCRIPT_DIR
    
    if not os.path.isdir(search_dir):
        return None

    # 候选文件名模式
    candidates = [
        f"pica8{script_name}.tcl",
        f"{script_name}.tcl",
    ]
    
    # 去掉末尾的 _XX_XX 数字后缀，得到 feature 关键词
    # 例如 FunStaticRoute_02_04 → FunStaticRoute
    feature_match = re.match(r"(.+?)_\d+_\d+$", script_name)
    feature_name = feature_match.group(1) if feature_match else script_name

    found_exact = None
    found_fuzzy = None

    for root, dirs, files in os.walk(search_dir):
        for f in files:
            if not f.endswith(".tcl"):
                continue
            f_lower = f.lower()
            # 精确匹配
            for cand in candidates:
                if f_lower == cand.lower():
                    return os.path.join(root, f)
            # 模糊匹配：文件名包含脚本名
            if script_name.lower() in f_lower:
                found_exact = os.path.join(root, f)
            # 更宽松：包含 feature 名
            elif feature_name.lower() in f_lower and found_fuzzy is None:
                found_fuzzy = os.path.join(root, f)

    return found_exact or found_fuzzy


class SourceViewer(ttk.Frame):
    """脚本源码查看器标签页"""

    def __init__(self, parent, script_name, search_dir=None):
        super().__init__(parent, padding=8)
        self.script_name = script_name
        self.search_dir = search_dir or DEFAULT_SCRIPT_DIR
        self._file_path = None
        self._raw_content = ""

        # 顶部信息
        info_frame = ttk.Frame(self)
        info_frame.pack(fill="x", pady=(0, 4))
        self.path_var = tk.StringVar(value="正在搜索脚本源码...")
        ttk.Label(info_frame, textvariable=self.path_var,
                  foreground="#888888", font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(info_frame, text="重新搜索", width=10,
                   command=self.reload).pack(side="right")
        self.save_btn = ttk.Button(info_frame, text="保存", width=8,
                                   command=self._save_file, state=tk.DISABLED)
        self.save_btn.pack(side="right", padx=4)
        self.edit_btn = ttk.Button(info_frame, text="编辑", width=8,
                                   command=self._toggle_edit)
        self.edit_btn.pack(side="right", padx=4)
        self._editing = False

        # 源码显示区
        code_frame = ttk.Frame(self)
        code_frame.pack(fill="both", expand=True)

        self.code_text = tk.Text(
            code_frame, wrap=tk.NONE, bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 10), state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )

        # 搜索框（在代码区上方）
        self.search_bar = SearchBar(code_frame, self.code_text)

        v_sb = ttk.Scrollbar(code_frame, orient=tk.VERTICAL, command=self.code_text.yview)
        h_sb = ttk.Scrollbar(code_frame, orient=tk.HORIZONTAL, command=self.code_text.xview)
        self.code_text.config(yscrollcommand=v_sb.set, xscrollcommand=h_sb.set)

        # 用 grid：搜索框 row=0（初始隐藏），代码 row=1
        self.code_text.grid(row=1, column=0, sticky="nsew")
        v_sb.grid(row=1, column=1, sticky="ns")
        h_sb.grid(row=2, column=0, sticky="ew")
        code_frame.rowconfigure(1, weight=1)
        code_frame.columnconfigure(0, weight=1)

        # 行号高亮
        self.code_text.tag_configure("lineno", foreground="#888888")
        self.code_text.tag_configure("hl_line", background="#3a3a00")

        # Ctrl+F / Ctrl+S
        self.bind_all("<Control-f>", lambda e: self.search_bar.toggle(), add="+")
        self.bind_all("<Control-s>", lambda e: self._save_file(), add="+")

        # 异步加载
        self.reload()

    def reload(self):
        self.path_var.set("正在搜索脚本源码...")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        path = find_script_file(self.script_name, self.search_dir)
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._file_path = path
                self.after(0, lambda: self._render(path, content))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"读取失败: {e}"))
        else:
            self.after(0, lambda: self._show_error(
                f"未找到脚本源码\n搜索目录: {self.search_dir}\n脚本名: {self.script_name}"))

    def _render(self, path, content):
        self.path_var.set(f"源码: {path}")
        self._raw_content = content
        self._show_readonly(content)

    def _show_readonly(self, content):
        """只读模式：带行号显示"""
        self.code_text.config(state=tk.NORMAL)
        self.code_text.delete("1.0", tk.END)
        for i, line in enumerate(content.splitlines(), 1):
            self.code_text.insert(tk.END, f"{i:>5} | ", "lineno")
            self.code_text.insert(tk.END, line + "\n")
        self.code_text.config(state=tk.DISABLED)

    def _toggle_edit(self):
        if not self._file_path:
            return
        if not self._editing:
            # 进入编辑模式：带行号显示，允许编辑
            self._editing = True
            self.edit_btn.config(text="取消编辑")
            self.save_btn.config(state=tk.NORMAL)
            self.code_text.config(state=tk.NORMAL)
            # 保留行号格式，用户直接编辑代码部分
            self.path_var.set(f"编辑中: {self._file_path}  (保存时行号会自动去除)")
        else:
            # 退出编辑模式：用原始内容恢复只读
            self._editing = False
            self.edit_btn.config(text="编辑")
            self.save_btn.config(state=tk.DISABLED)
            self._show_readonly(self._raw_content)
            self.path_var.set(f"源码: {self._file_path}")

    def _save_file(self):
        if not self._file_path or not self._editing:
            return
        # 从编辑区提取内容，去掉行号前缀 "   5 | "
        import re
        raw = self.code_text.get("1.0", "end-1c")
        lines = []
        for line in raw.splitlines():
            # 去掉 "  123 | " 格式的行号前缀
            cleaned = re.sub(r"^\s*\d+\s*\|\s?", "", line, count=1)
            lines.append(cleaned)
        content = "\n".join(lines)
        try:
            with open(self._file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            self._raw_content = content
            self.path_var.set(f"✓ 已保存: {self._file_path}")
        except Exception as e:
            self.path_var.set(f"✗ 保存失败: {e}")

    def _show_error(self, msg):
        self.path_var.set("未找到源码")
        self.code_text.config(state=tk.NORMAL)
        self.code_text.delete("1.0", tk.END)
        self.code_text.insert(tk.END, msg)
        self.code_text.config(state=tk.DISABLED)

    def goto_line(self, line_no):
        """跳转到指定行并高亮"""
        self.code_text.tag_remove("hl_line", "1.0", tk.END)
        # 每行在 Text 里占 1 行（行号 + 内容）
        target = f"{line_no}.0"
        try:
            self.code_text.tag_add("hl_line", target, f"{line_no}.end")
            self.code_text.see(target)
        except tk.TclError:
            pass
