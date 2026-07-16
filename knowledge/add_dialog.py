"""添加知识库条目对话框（增强版：AI辅助填写 + 去重提醒）"""

import re
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from .. import theme
from .models import KBEntry, CATEGORIES
from .storage import add_entry, load_kb


def show_add_dialog(parent, analysis=None, script_name="", ssh_user=""):
    """弹出添加知识库对话框

    analysis: 当前分析结果（用于预填）
    script_name: 当前脚本名
    ssh_user: 提交人（从登录界面的 SSH_USER 读取）
    """
    win = tk.Toplevel(parent)
    win.title("添加到知识库")
    win.geometry("700x620")
    theme.apply(win)

    container = ttk.Frame(win, padding=12)
    container.pack(fill="both", expand=True)

    # ---- 自动预填信息 ----
    auto_script = script_name or ""
    auto_step = ""
    if analysis and analysis.get("fail_contexts"):
        fc = analysis["fail_contexts"][0]
        if fc.get("step"):
            auto_step = f"Step {fc['step']['step_no']}: {fc['step']['step_desc']}"
    auto_fail_line = ""
    if analysis and analysis.get("failures"):
        auto_fail_line = analysis["failures"][0][1]
    auto_expected_got = ""
    if analysis and analysis.get("fail_contexts"):
        fc = analysis["fail_contexts"][0]
        if fc.get("phenomenon"):
            auto_expected_got = fc["phenomenon"]

    # ---- UI 字段 ----
    row = 0

    # 脚本名
    ttk.Label(container, text="脚本名：").grid(row=row, column=0, sticky="nw", pady=3)
    script_var = tk.StringVar(value=auto_script)
    ttk.Entry(container, textvariable=script_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 所属 Step
    ttk.Label(container, text="所属 Step：").grid(row=row, column=0, sticky="nw", pady=3)
    step_var = tk.StringVar(value=auto_step)
    ttk.Entry(container, textvariable=step_var, state="readonly").grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 失败具体位置
    ttk.Label(container, text="失败具体位置：").grid(row=row, column=0, sticky="nw", pady=3)
    fail_loc_text = tk.Text(container, height=3, font=("Consolas", 9),
                            bg="#2b2b2b", fg="#e0e0e0", insertbackground="#e0e0e0")
    fail_loc_text.grid(row=row, column=1, sticky="ew", pady=3, columnspan=2)
    fail_loc_text.insert("1.0", auto_fail_line)
    row += 1

    # 匹配模式
    ttk.Label(container, text="匹配模式（正则/关键词）：").grid(row=row, column=0, sticky="nw", pady=3)
    pattern_var = tk.StringVar()
    if auto_fail_line:
        m = re.search(r"(Fail.*?)(?:\}|$)", auto_fail_line, re.I)
        if m:
            pattern_var.set(m.group(1)[:100])
    ttk.Entry(container, textvariable=pattern_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 失败原因
    ttk.Label(container, text="失败原因：").grid(row=row, column=0, sticky="nw", pady=3)
    cause_var = tk.StringVar()
    ttk.Entry(container, textvariable=cause_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 解决方法
    ttk.Label(container, text="解决方法（可选）：").grid(row=row, column=0, sticky="nw", pady=3)
    solution_var = tk.StringVar()
    ttk.Entry(container, textvariable=solution_var, font=("Consolas", 9)).grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 分类
    ttk.Label(container, text="分类：").grid(row=row, column=0, sticky="nw", pady=3)
    category_var = tk.StringVar(value="其他")
    ttk.Combobox(container, textvariable=category_var,
                 values=CATEGORIES, width=20, state="readonly").grid(
        row=row, column=1, sticky="w", pady=3)
    row += 1

    # 提交人
    ttk.Label(container, text="提交人：").grid(row=row, column=0, sticky="nw", pady=3)
    user_var = tk.StringVar(value=ssh_user)
    ttk.Entry(container, textvariable=user_var).grid(
        row=row, column=1, sticky="ew", pady=3, columnspan=2)
    row += 1

    # 去重提醒区域
    dup_frame = ttk.LabelFrame(container, text="  相似条目检测  ", padding=6)
    dup_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 0))
    dup_label = ttk.Label(dup_frame, text="保存时自动检测", foreground="#888888")
    dup_label.pack(anchor="w")
    row += 1

    container.columnconfigure(1, weight=1)

    # ---- 按钮 ----
    btn_frame = ttk.Frame(container)
    btn_frame.grid(row=row, column=0, columnspan=3, pady=(12, 0), sticky="ew")

    # AI 生成状态
    ai_status_var = tk.StringVar(value="")
    ttk.Label(btn_frame, textvariable=ai_status_var,
              foreground="#0078d4").pack(side="bottom", anchor="w", pady=(4, 0))

    def _ai_fill():
        """AI辅助填写：自动生成失败原因、匹配模式、分类"""
        fail_text = fail_loc_text.get("1.0", tk.END).strip()
        if not fail_text:
            messagebox.showwarning("无内容", "请先确认失败具体位置", parent=win)
            return
        ai_status_var.set("● AI 正在分析...")
        ai_btn.config(state=tk.DISABLED)

        def _worker():
            try:
                from openai import OpenAI
                from ..config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
                if not DEEPSEEK_API_KEY:
                    win.after(0, lambda: ai_status_var.set("✗ 未配置 API Key"))
                    win.after(0, lambda: ai_btn.config(state=tk.NORMAL))
                    return

                client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
                prompt = f"""分析以下自动化测试脚本的失败日志行,提取信息:

失败位置: {fail_text}
脚本名: {auto_script}
Step: {auto_step}

请严格按以下JSON格式回答(不要加```json标记):
{{"pattern": "用于匹配此类失败的正则表达式(简短精确)", "cause": "失败根因(一句话中文)", "solution": "解决方法(一句话,可选)", "category": "从以下选择: 环境问题/功能bug/时序问题/脚本问题/配置问题/硬件问题/随机性问题/其他"}}"""

                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                )
                content = resp.choices[0].message.content.strip()

                import json
                # 尝试解析JSON
                data = json.loads(content)

                def _apply():
                    if data.get("pattern"):
                        pattern_var.set(data["pattern"])
                    if data.get("cause"):
                        cause_var.set(data["cause"])
                    if data.get("solution"):
                        solution_var.set(data["solution"])
                    if data.get("category") and data["category"] in CATEGORIES:
                        category_var.set(data["category"])
                    ai_status_var.set("✓ AI 已填写,请确认后保存")
                    ai_btn.config(state=tk.NORMAL)

                win.after(0, _apply)

            except Exception as e:
                err = str(e)
                win.after(0, lambda: ai_status_var.set(f"✗ AI 分析失败: {err[:50]}"))
                win.after(0, lambda: ai_btn.config(state=tk.NORMAL))

        threading.Thread(target=_worker, daemon=True).start()

    def _check_duplicate():
        """P3: 检查是否有相似条目"""
        pattern = pattern_var.get().strip()
        cause = cause_var.get().strip()
        if not pattern and not cause:
            return None

        entries = load_kb()
        similar = []
        for e in entries:
            # 检查 pattern 相似
            if pattern and e.pattern:
                if pattern.lower() in e.pattern.lower() or e.pattern.lower() in pattern.lower():
                    similar.append(e)
                    continue
            # 检查 cause 关键词重合
            if cause and e.cause:
                cause_words = set(cause.lower().split())
                entry_words = set(e.cause.lower().split())
                overlap = cause_words & entry_words
                if len(overlap) >= 3:
                    similar.append(e)
        return similar[:3]  # 最多返回3条

    def _save():
        p = pattern_var.get().strip()
        c = cause_var.get().strip()
        if not p or not c:
            messagebox.showwarning("输入不完整", "匹配模式和失败原因必填", parent=win)
            return

        # P3: 去重检查
        similar = _check_duplicate()
        if similar:
            dup_msgs = []
            for s in similar:
                dup_msgs.append(f"• [{s.category}] {s.cause[:40]}")
            msg = "发现相似条目:\n\n" + "\n".join(dup_msgs) + "\n\n确定仍要添加?"
            if not messagebox.askyesno("相似条目提醒", msg, parent=win):
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
        messagebox.showinfo("成功", "已添加到知识库", parent=win)
        win.destroy()

    ai_btn = ttk.Button(btn_frame, text="AI 生成", command=_ai_fill)
    ai_btn.pack(side="left")
    ttk.Button(btn_frame, text="保存", style="Accent.TButton", command=_save).pack(side="left", padx=8)
    ttk.Button(btn_frame, text="取消", command=win.destroy).pack(side="left", padx=4)
