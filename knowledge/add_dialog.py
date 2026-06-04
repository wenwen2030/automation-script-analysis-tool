"""添加知识库条目对话框（增强版）"""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from .. import theme
from .models import KBEntry, CATEGORIES
from .storage import add_entry


def show_add_dialog(parent, analysis=None, script_name="", ssh_user=""):
    """弹出添加知识库对话框

    analysis: 当前分析结果（用于预填）
    script_name: 当前脚本名
    ssh_user: 提交人（从登录界面的 SSH_USER 读取）
    """
    win = tk.Toplevel(parent)
    win.title("添加到知识库")
    win.geometry("650x550")
    theme.apply(win)

    container = ttk.Frame(win, padding=12)
    container.pack(fill="both", expand=True)

    # ---- 自动预填信息 ----
    # 脚本名
    auto_script = script_name or ""
    # Step
    auto_step = ""
    if analysis and analysis.get("fail_contexts"):
        fc = analysis["fail_contexts"][0]
        if fc.get("step"):
            auto_step = f"Step {fc['step']['step_no']}: {fc['step']['step_desc']}"
    # 失败具体位置（第一个 Fail 行）
    auto_fail_line = ""
    if analysis and analysis.get("failures"):
        auto_fail_line = analysis["failures"][0][1]  # 第一个 fail 行内容
    # Expected / Got
    auto_expected_got = ""
    if analysis and analysis.get("fail_contexts"):
        fc = analysis["fail_contexts"][0]
        if fc.get("phenomenon"):
            auto_expected_got = fc["phenomenon"]

    # ---- UI 字段 ----
    row = 0

    # 脚本名（自动）
    ttk.Label(container, text="脚本名：").grid(row=row, column=0, sticky="nw", pady=3)
    script_var = tk.StringVar(value=auto_script)
    ttk.Entry(container, textvariable=script_var, state="readonly").grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    # 所属 Step（自动）
    ttk.Label(container, text="所属 Step：").grid(row=row, column=0, sticky="nw", pady=3)
    step_var = tk.StringVar(value=auto_step)
    ttk.Entry(container, textvariable=step_var, state="readonly").grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    # 失败具体位置（可编辑，预填第一个 Fail 行）
    ttk.Label(container, text="失败具体位置：").grid(row=row, column=0, sticky="nw", pady=3)
    fail_loc_text = tk.Text(container, height=3, font=("Consolas", 9),
                            bg="#2b2b2b", fg="#e0e0e0", insertbackground="#e0e0e0")
    fail_loc_text.grid(row=row, column=1, sticky="ew", pady=3)
    fail_loc_text.insert("1.0", auto_fail_line)
    row += 1

    # 匹配模式
    ttk.Label(container, text="匹配模式（正则/关键词）：").grid(row=row, column=0, sticky="nw", pady=3)
    pattern_var = tk.StringVar()
    # 预填：从 Fail 行提取关键部分
    if auto_fail_line:
        import re
        m = re.search(r"(Fail.*?)(?:\}|$)", auto_fail_line, re.I)
        if m:
            pattern_var.set(m.group(1)[:100])
    ttk.Entry(container, textvariable=pattern_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    # 失败原因（根因描述）
    ttk.Label(container, text="失败原因：").grid(row=row, column=0, sticky="nw", pady=3)
    cause_var = tk.StringVar()
    ttk.Entry(container, textvariable=cause_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    # 解决方法
    ttk.Label(container, text="解决方法（可选）：").grid(row=row, column=0, sticky="nw", pady=3)
    solution_var = tk.StringVar()
    ttk.Entry(container, textvariable=solution_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    # 分类
    ttk.Label(container, text="分类：").grid(row=row, column=0, sticky="nw", pady=3)
    category_var = tk.StringVar(value="其他")
    ttk.Combobox(container, textvariable=category_var,
                 values=CATEGORIES, width=20, state="readonly").grid(
        row=row, column=1, sticky="w", pady=3)
    row += 1

    # 提交人（自动从 SSH_USER 读取）
    ttk.Label(container, text="提交人：").grid(row=row, column=0, sticky="nw", pady=3)
    user_var = tk.StringVar(value=ssh_user)
    ttk.Entry(container, textvariable=user_var).grid(
        row=row, column=1, sticky="ew", pady=3)
    row += 1

    container.columnconfigure(1, weight=1)

    # ---- 按钮 ----
    btn_frame = ttk.Frame(container)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=(12, 0), sticky="ew")

    def _save():
        p = pattern_var.get().strip()
        c = cause_var.get().strip()
        if not p or not c:
            messagebox.showwarning("输入不完整", "匹配模式和失败原因必填", parent=win)
            return
        entry = KBEntry(
            pattern=p,
            cause=c,
            solution=solution_var.get().strip(),
            category=category_var.get(),
            script_name=auto_script,
            step_info=step_var.get(),
            added_by=user_var.get().strip(),
        )
        add_entry(entry)
        messagebox.showinfo("成功", f"已添加到知识库", parent=win)
        win.destroy()

    ttk.Button(btn_frame, text="保存", style="Accent.TButton", command=_save).pack(side="left")
    ttk.Button(btn_frame, text="取消", command=win.destroy).pack(side="left", padx=8)
