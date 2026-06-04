"""知识库管理窗口：查看、编辑、删除条目"""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from .. import theme
from .models import KBEntry, CATEGORIES
from .storage import load_kb, save_kb, delete_entry


def show_manager_dialog(parent):
    """弹出知识库管理窗口"""
    win = tk.Toplevel(parent)
    win.title("知识库管理")
    win.geometry("900x500")
    theme.apply(win)

    entries = load_kb()

    container = ttk.Frame(win, padding=10)
    container.pack(fill="both", expand=True)

    # 顶部统计
    stats_var = tk.StringVar(value=f"共 {len(entries)} 条记录")
    ttk.Label(container, textvariable=stats_var,
              font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

    # 列表
    columns = ("pattern", "cause", "category", "hits", "added_at")
    tree = ttk.Treeview(container, columns=columns, show="headings", height=15)
    tree.heading("pattern", text="匹配模式")
    tree.heading("cause", text="根因描述")
    tree.heading("category", text="分类")
    tree.heading("hits", text="命中")
    tree.heading("added_at", text="添加时间")
    tree.column("pattern", width=200, minwidth=100)
    tree.column("cause", width=250, minwidth=100)
    tree.column("category", width=80, minwidth=60, anchor="center")
    tree.column("hits", width=50, minwidth=40, anchor="center")
    tree.column("added_at", width=120, minwidth=80, anchor="center")

    sb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
    tree.config(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")

    def _refresh():
        nonlocal entries
        entries = load_kb()
        tree.delete(*tree.get_children())
        for e in entries:
            tree.insert("", "end", values=(
                e.pattern[:60], e.cause[:60], e.category,
                e.hit_count, e.added_at
            ))
        stats_var.set(f"共 {len(entries)} 条记录")

    _refresh()

    # 底部按钮
    btn_frame = ttk.Frame(win, padding=8)
    btn_frame.pack(fill="x")

    def _delete():
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        if messagebox.askyesno("确认删除", f"确定删除第 {idx+1} 条？", parent=win):
            delete_entry(idx)
            _refresh()

    def _view_detail():
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        if idx < len(entries):
            e = entries[idx]
            detail = (
                f"匹配模式: {e.pattern}\n"
                f"根因描述: {e.cause}\n"
                f"解决方法: {e.solution}\n"
                f"分类: {e.category}\n"
                f"来源脚本: {e.script_name}\n"
                f"来源 Step: {e.step_info}\n"
                f"添加人: {e.added_by}\n"
                f"添加时间: {e.added_at}\n"
                f"命中次数: {e.hit_count}"
            )
            messagebox.showinfo("条目详情", detail, parent=win)

    ttk.Button(btn_frame, text="查看详情", command=_view_detail).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="删除选中", command=_delete).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="刷新", command=_refresh).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="关闭", command=win.destroy).pack(side="right", padx=4)
