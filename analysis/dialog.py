"""分析窗口主 UI：整合搜索、Fail 跳转、历史、导出"""

import os
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox, simpledialog

from .. import theme
from .analyzer import analyze_remote
from .search_bar import SearchBar
from .source_viewer import SourceViewer
from ..knowledge import match_knowledge, set_ssh_info as kb_set_ssh_info
from ..knowledge.add_dialog import show_add_dialog
from ..knowledge.manager_dialog import show_manager_dialog
from ..knowledge.importer import import_from_file as kb_import
from .highlighter import configure_tags as hl_configure_tags, highlight_text
from .config_extractor import extract_configs_by_step, format_steps_for_display
from .ai_chat import AiChatTab


class AnalysisDialog:
    def __init__(self, parent, host, user, password, monitor_dir, script_name):
        self.parent = parent
        self.host = host
        self.user = user
        self.password = password
        self.monitor_dir = monitor_dir.rstrip("/")
        self.script_name = script_name
        self.log_file = f"{self.monitor_dir}/{script_name}.txt"
        self._analysis = None
        self._raw_text = ""

        self.top = tk.Toplevel(parent)
        self.top.title(f"失败分析 — {script_name}")
        self.top.geometry("1000x700")
        theme.apply(self.top)

        self._build_ui()
        # 设置知识库的 SSH 连接信息（用于远程读写）
        kb_set_ssh_info(self.host, self.user, self.password)
        threading.Thread(target=self._do_analyze, daemon=True).start()

    def _build_ui(self):
        container = ttk.Frame(self.top, padding=10)
        container.pack(fill="both", expand=True)

        # 顶部信息条
        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 8))
        self.header_script_var = tk.StringVar(value=f"脚本: {self.script_name}")
        ttk.Label(header, textvariable=self.header_script_var,
                  font=("Segoe UI", 10, "bold")).pack(side="left")
        self.header_log_var = tk.StringVar(value=f"  日志: {self.log_file}")
        ttk.Label(header, textvariable=self.header_log_var,
                  foreground="#888888", font=("Segoe UI", 9)).pack(side="left")
        self.status_var = tk.StringVar(value="● 正在下载并分析日志...")
        ttk.Label(header, textvariable=self.status_var,
                  foreground="#0078d4").pack(side="right")

        # ---- 底部按钮（先占位）----
        btn_frame = ttk.Frame(container)
        btn_frame.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(btn_frame, text="重新分析", command=self._reanalyze).pack(side="left")
        ttk.Button(btn_frame, text="添加到知识库", command=self._add_to_kb).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="管理知识库", command=self._manage_kb).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="导入知识库", command=self._import_kb).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="关闭", command=self.top.destroy).pack(side="right")

        # ---- 主体：左右分割（左=文件列表，右=分析内容）----
        main_paned = ttk.PanedWindow(container, orient=tk.HORIZONTAL)
        main_paned.pack(fill="both", expand=True)

        # 左侧：远程日志文件列表
        left_frame = ttk.LabelFrame(main_paned, text="  日志文件  ", padding=6)
        top_row = ttk.Frame(left_frame)
        top_row.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(top_row, text="刷新列表", width=10,
                   command=self._refresh_file_list).pack(side="left")
        # 文件名过滤搜索框
        self.file_filter_var = tk.StringVar()
        self.file_filter_var.trace_add("write", lambda *_: self._apply_file_filter())
        filter_entry = ttk.Entry(top_row, textvariable=self.file_filter_var,
                                 font=("Consolas", 9))
        filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        # 占位提示
        filter_entry.insert(0, "")
        lb_frame = ttk.Frame(left_frame)
        lb_frame.pack(fill="both", expand=True)
        pal = theme.palette()
        self.file_listbox = tk.Listbox(
            lb_frame, width=30, font=("Consolas", 9),
            bg=pal["bg"], fg=pal["fg"],
            selectbackground=pal["select_bg"], selectforeground=pal["select_fg"],
            borderwidth=1, relief="solid", highlightthickness=0,
        )
        file_sb = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=file_sb.set)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        file_sb.pack(side="left", fill="y")
        self.file_listbox.bind("<Double-1>", self._on_file_double_click)
        main_paned.add(left_frame, weight=1)

        # 右侧：Notebook（分析内容）
        right_frame = ttk.Frame(main_paned)

        self.nb = ttk.Notebook(right_frame)
        self.nb.pack(fill="both", expand=True)

        # ---- 诊断摘要 ----
        summary_tab = ttk.Frame(self.nb, padding=8)
        self.summary_text = tk.Text(
            summary_tab, wrap=tk.WORD, bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 10), state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        s_sb = ttk.Scrollbar(summary_tab, orient=tk.VERTICAL, command=self.summary_text.yview)
        self.summary_text.config(yscrollcommand=s_sb.set)
        self.summary_text.pack(side="left", fill="both", expand=True)
        s_sb.pack(side="left", fill="y")
        self.summary_text.tag_configure("title", foreground="#dcdcaa", font=("Consolas", 11, "bold"))
        self.summary_text.tag_configure("error", foreground="#f44747")
        self.summary_text.tag_configure("ok", foreground="#6a9955")
        self.summary_text.tag_configure("hint", foreground="#9cdcfe")
        self.summary_text.tag_configure("lineno", foreground="#888888")
        self.nb.add(summary_tab, text="  脚本日志分析  ")

        # ---- 完整日志（含搜索框）----
        log_tab = ttk.Frame(self.nb, padding=8)
        self.log_text = tk.Text(
            log_tab, wrap=tk.CHAR, bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        # 配置语法高亮 tag
        hl_configure_tags(self.log_text)
        l_v = ttk.Scrollbar(log_tab, orient=tk.VERTICAL, command=self.log_text.yview)
        l_h = ttk.Scrollbar(log_tab, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.config(yscrollcommand=l_v.set, xscrollcommand=l_h.set)
        # 搜索框（初始隐藏，Ctrl+F 显示）
        self.search_bar = SearchBar(log_tab, self.log_text)
        # 布局：搜索框 row=0，日志 row=1
        self.log_text.grid(row=1, column=0, sticky="nsew")
        l_v.grid(row=1, column=1, sticky="ns")
        l_h.grid(row=2, column=0, sticky="ew")
        log_tab.rowconfigure(1, weight=1)
        log_tab.columnconfigure(0, weight=1)
        self.nb.add(log_tab, text="  完整日志  ")

        # ---- 脚本源码 ----
        try:
            self.source_viewer = SourceViewer(self.nb, self.script_name)
            self.nb.add(self.source_viewer, text="  脚本源码  ")
        except Exception as e:
            self.source_viewer = None
            import traceback
            traceback.print_exc()

        # ---- 配置提取 ----
        cfg_tab = ttk.Frame(self.nb, padding=8)
        self.cfg_text = tk.Text(
            cfg_tab, wrap=tk.NONE, bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 10), state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        cfg_v = ttk.Scrollbar(cfg_tab, orient=tk.VERTICAL, command=self.cfg_text.yview)
        cfg_h = ttk.Scrollbar(cfg_tab, orient=tk.HORIZONTAL, command=self.cfg_text.xview)
        self.cfg_text.config(yscrollcommand=cfg_v.set, xscrollcommand=cfg_h.set)
        self.cfg_text.grid(row=0, column=0, sticky="nsew")
        cfg_v.grid(row=0, column=1, sticky="ns")
        cfg_h.grid(row=1, column=0, sticky="ew")
        cfg_tab.rowconfigure(0, weight=1)
        cfg_tab.columnconfigure(0, weight=1)
        # 配置提取的高亮 tag
        self.cfg_text.tag_configure("step_title", foreground="#dcdcaa", font=("Consolas", 10, "bold"))
        self.cfg_text.tag_configure("sep", foreground="#555555")
        self.cfg_text.tag_configure("marker", foreground="#9cdcfe", font=("Consolas", 10, "bold"))
        self.cfg_text.tag_configure("cmd_set", foreground="#6a9955")
        self.cfg_text.tag_configure("cmd_del", foreground="#f44747")
        self.cfg_text.tag_configure("cmd_other", foreground="#d4d4d4")
        self.cfg_text.tag_configure("cmd_view", foreground="#9cdcfe")
        self.nb.add(cfg_tab, text="  配置提取  ")

        # ---- AI 分析 ----
        self.ai_chat = AiChatTab(
            self.nb,
            get_log_fn=lambda: getattr(self, "_raw_text", ""),
            get_script_name_fn=lambda: self.script_name,
        )
        self.nb.add(self.ai_chat, text="  AI 分析  ")

        # Ctrl+F 绑定
        self.top.bind("<Control-f>", lambda e: self._handle_ctrl_f())

        main_paned.add(right_frame, weight=3)

        # 异步加载文件列表
        self._refresh_file_list()

    # ---- 文件列表操作 ----

    def _refresh_file_list(self):
        """从远程 monitor_dir 获取 .txt 文件列表"""
        threading.Thread(target=self._load_file_list, daemon=True).start()

    def _load_file_list(self):
        try:
            from .analyzer import _get_ssh_client
            client = _get_ssh_client(self.host, self.user, self.password)
            _, stdout, _ = client.exec_command(
                f"ls -t {self.monitor_dir}/*.txt 2>/dev/null")
            output = stdout.read().decode("utf-8", errors="replace")
            files = [os.path.basename(f.strip()) for f in output.splitlines() if f.strip()]
            self.top.after(0, lambda: self._populate_file_list(files))
        except Exception as e:
            err = str(e)
            self.top.after(0, lambda: self._populate_file_list([f"(加载失败: {err})"]))

    def _populate_file_list(self, files):
        self._all_files = files  # 保存全量
        self._apply_file_filter()

    def _apply_file_filter(self):
        keyword = self.file_filter_var.get().strip().lower()
        self.file_listbox.delete(0, tk.END)
        for f in getattr(self, "_all_files", []):
            if not keyword or keyword in f.lower():
                self.file_listbox.insert(tk.END, f)

    def _on_file_double_click(self, event):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        filename = self.file_listbox.get(sel[0])
        if filename.startswith("("):
            return  # 错误提示行，忽略
        # 去掉 .txt 后缀作为脚本名
        script_name = filename[:-4] if filename.endswith(".txt") else filename
        self._switch_to_script(script_name)

    def _switch_to_script(self, script_name):
        self.script_name = script_name
        self.log_file = f"{self.monitor_dir}/{script_name}.txt"
        self.top.title(f"失败分析 — {script_name}")
        self.header_script_var.set(f"脚本: {script_name}")
        self.header_log_var.set(f"  日志: {self.log_file}")
        if self.source_viewer:
            self.source_viewer.script_name = script_name
            self.source_viewer.reload()
        self.status_var.set("● 正在下载并分析日志...")
        threading.Thread(target=self._do_analyze, daemon=True).start()

    # ---- 分析逻辑 ----

    # ---- 分析逻辑 ----

    def _do_analyze(self):
        try:
            # 第一步：下载日志（这是最快的，先把日志显示出来）
            from .analyzer import ssh_read_file
            raw_text = ssh_read_file(
                self.host, self.user, self.password, self.log_file)
            self._raw_text = raw_text
            # 立即渲染完整日志并切到该标签页
            self.top.after(0, lambda: self._render_log_first(raw_text))

            # 第二步：跑分析（耗时操作）
            from .analyzer import analyze
            analysis = analyze(raw_text, script_name=self.script_name)
            self._analysis = analysis
            self.top.after(0, lambda: self._render_analysis(analysis, raw_text))
        except Exception as e:
            err = str(e)
            self.top.after(0, lambda: self._show_error(f"读取/分析失败: {err}"))
            return

    def _render_log_first(self, raw_text):
        """先把完整日志显示出来，让用户能立即查看"""
        self._set_text(self.log_text, raw_text)
        # 大文件跳过全文高亮
        if len(raw_text) < 200000:
            highlight_text(self.log_text)
        # 切到完整日志标签
        try:
            self.nb.select(1)
        except Exception:
            pass
        # 如果搜索框有内容，自动重新搜索当前日志
        if hasattr(self, "search_bar") and self.search_bar.search_var.get():
            self.search_bar._on_search()
        self.status_var.set("● 日志已加载，正在分析...")

    def _render_analysis(self, a, raw_text):
        """渲染分析结果（脚本日志分析 + 配置提取）"""
        self._render_summary(a)
        self._render_configs(raw_text)
        if a["result"] == "pass":
            self.status_var.set("✓ 分析完成（脚本通过）")
        else:
            self.status_var.set(f"⚠ 分析完成（{a['result']}）")

    def _render_summary(self, a):
        # 摘要
        self._set_text(self.summary_text, "")
        self.summary_text.config(state=tk.NORMAL)
        self.summary_text.insert(tk.END, "脚本日志分析\n", "title")
        self.summary_text.insert(tk.END, "=" * 60 + "\n")
        result_tag = "ok" if a["result"] == "pass" else "error"
        self.summary_text.insert(tk.END, f"测试结果: {a['result'].upper()}\n", result_tag)
        if a["meta"]["title"]:
            self.summary_text.insert(tk.END, f"测试目标: {a['meta']['title']}\n")
        if a["meta"]["description"]:
            self.summary_text.insert(tk.END, f"测试描述: {a['meta']['description']}\n")
        self.summary_text.insert(tk.END, "\n")

        if a["failures"]:
            self.summary_text.insert(tk.END,
                f"失败/错误关键行（共 {len(a['failures'])} 条）:\n", "title")
            for ln, line in a["failures"][:15]:
                self.summary_text.insert(tk.END, f"  L{ln}: ", "lineno")
                self.summary_text.insert(tk.END, line + "\n", "error")
            self.summary_text.insert(tk.END, "\n")

            # 每个 fail 点的详细信息：所属 Step + 现象 + 组包
            self.summary_text.insert(tk.END, "失败点详细分析\n", "title")
            for idx, fc in enumerate(a.get("fail_contexts", []), 1):
                self.summary_text.insert(tk.END, f"\n[失败点 {idx}] L{fc['line_no']}  ", "title")
                # 嵌入"加入知识库"按钮
                add_btn = ttk.Button(self.summary_text, text="+知识库",
                                     command=lambda fc=fc, idx=idx: self._add_fail_to_kb(fc, idx))
                self.summary_text.window_create(tk.END, window=add_btn)
                self.summary_text.insert(tk.END, "\n")
                # Step 信息
                if fc.get("step"):
                    s = fc["step"]
                    self.summary_text.insert(tk.END,
                        f"  所属 Step: Step {s['step_no']}  ", "hint")
                    self.summary_text.insert(tk.END, f"{s['step_desc']}\n", "ok")
                else:
                    self.summary_text.insert(tk.END, "  所属 Step: (未识别)\n", "lineno")
                # 失败现象
                if fc.get("phenomenon"):
                    self.summary_text.insert(tk.END, "  失败现象:\n", "hint")
                    for line in fc["phenomenon"].splitlines():
                        self.summary_text.insert(tk.END, f"    {line}\n", "error")
                # 组包信息
                if fc.get("packet"):
                    p = fc["packet"]
                    self.summary_text.insert(tk.END, "  发包构造:\n", "hint")
                    if p.get("stream"):
                        self.summary_text.insert(tk.END, f"    stream:   {p['stream']}\n")
                    if p.get("protocol"):
                        self.summary_text.insert(tk.END, f"    protocol: {p['protocol']}\n")
                    if p.get("ip"):
                        self.summary_text.insert(tk.END, f"    ip:       {p['ip']}\n")
            self.summary_text.insert(tk.END, "\n")

        if a["expected"] or a["got"]:
            self.summary_text.insert(tk.END, "Expected vs Got\n", "title")
            if a["expected"]:
                self.summary_text.insert(tk.END, f"  Expected: {a['expected']}\n", "ok")
            if a["got"]:
                self.summary_text.insert(tk.END, f"  Got:      {a['got']}\n", "error")
            self.summary_text.insert(tk.END, "\n")

        if a["timeouts"]:
            self.summary_text.insert(tk.END, f"超时/异常命令（{len(a['timeouts'])} 次）\n", "title")
            for t in a["timeouts"][:5]:
                if "ip" in t:
                    self.summary_text.insert(tk.END, f"  {t['ip']} csl={t['csl']}\n", "error")
                else:
                    self.summary_text.insert(tk.END, f"  {t['raw'][:120]}\n", "error")
            self.summary_text.insert(tk.END, "\n")

        if a["hints"]:
            self.summary_text.insert(tk.END, "可能根因\n", "title")
            for h in a["hints"]:
                self.summary_text.insert(tk.END, f"  • {h}\n", "hint")

        if a.get("kb_matches"):
            self.summary_text.insert(tk.END, "\n已知问题（知识库匹配）\n", "title")
            for km in a["kb_matches"]:
                cause = km.cause if hasattr(km, "cause") else km.get("cause", "")
                solution = km.solution if hasattr(km, "solution") else km.get("solution", "")
                category = km.category if hasattr(km, "category") else km.get("category", "")
                hits = km.hit_count if hasattr(km, "hit_count") else km.get("hit_count", 0)
                self.summary_text.insert(tk.END, f"  ★ [{category}] {cause}", "error")
                if hits > 0:
                    self.summary_text.insert(tk.END, f"  (命中 {hits} 次)", "lineno")
                self.summary_text.insert(tk.END, "\n")
                if solution:
                    self.summary_text.insert(tk.END, f"    解决: {solution}\n", "hint")

        self.summary_text.config(state=tk.DISABLED)

    # ---- 操作按钮 ----

    def _reanalyze(self):
        self.status_var.set("● 正在重新分析...")
        threading.Thread(target=self._do_analyze, daemon=True).start()

    def _add_to_kb(self):
        """弹出增强版添加知识库对话框"""
        show_add_dialog(self.top, analysis=self._analysis,
                        script_name=self.script_name, ssh_user=self.user)

    def _add_fail_to_kb(self, fail_context, idx):
        """针对单个失败点弹出添加知识库对话框(预填该失败点信息)"""
        # 构造一个只包含这个失败点的伪analysis对象
        single_analysis = {
            "result": self._analysis.get("result", "fail") if self._analysis else "fail",
            "failures": [],
            "fail_contexts": [fail_context],
            "expected": "",
            "got": "",
            "timeouts": [],
            "hints": [],
            "meta": self._analysis.get("meta", {}) if self._analysis else {},
        }
        # 如果这个fail_context有对应的failure行
        if fail_context.get("line_no"):
            for ln, line in (self._analysis or {}).get("failures", []):
                if ln == fail_context["line_no"]:
                    single_analysis["failures"] = [(ln, line)]
                    break
        show_add_dialog(self.top, analysis=single_analysis,
                        script_name=self.script_name, ssh_user=self.user)

    def _manage_kb(self):
        """打开知识库管理窗口"""
        show_manager_dialog(self.top)

    def _import_kb(self):
        """从文件导入知识库"""
        kb_import(self.top)

    def _render_configs(self, raw_text):
        """提取并渲染按 Step 分组的配置命令"""
        steps = extract_configs_by_step(raw_text)
        self.cfg_text.config(state=tk.NORMAL)
        self.cfg_text.delete("1.0", tk.END)
        if not steps:
            self.cfg_text.insert(tk.END, "未在日志中提取到任何配置命令\n")
            self.cfg_text.config(state=tk.DISABLED)
            return
        for s in steps:
            self.cfg_text.insert(tk.END, "=" * 80 + "\n", "sep")
            self.cfg_text.insert(tk.END, f"Step {s['step_no']}: {s['step_desc']}\n", "step_title")
            self.cfg_text.insert(tk.END, "=" * 80 + "\n", "sep")

            # 分类命令
            config_cmds = []  # set / delete / commit / configure / edit / rollback / load / save / exit
            view_cmds = []    # run / show

            for cmd in s["commands"]:
                cmd_low = cmd.lstrip()
                if cmd_low.startswith("run ") or cmd_low.startswith("show "):
                    view_cmds.append(cmd)
                else:
                    config_cmds.append(cmd)

            # 配置命令区
            if config_cmds:
                self.cfg_text.insert(tk.END, ">>> [PICOS 配置] <<<\n", "marker")
                for cmd in config_cmds:
                    if cmd.startswith("set "):
                        tag = "cmd_set"
                    elif cmd.startswith("delete "):
                        tag = "cmd_del"
                    else:
                        tag = "cmd_other"
                    self.cfg_text.insert(tk.END, cmd + "\n", tag)
                self.cfg_text.insert(tk.END, "\n")

            # 查看命令区
            if view_cmds:
                self.cfg_text.insert(tk.END, ">>> [PICOS 查看] <<<\n", "marker")
                for cmd in view_cmds:
                    self.cfg_text.insert(tk.END, cmd + "\n", "cmd_view")
                self.cfg_text.insert(tk.END, "\n")

        self.cfg_text.config(state=tk.DISABLED)

    # ---- 工具方法 ----

    def _handle_ctrl_f(self):
        """根据当前标签页切换对应的搜索框"""
        current_tab = self.nb.index(self.nb.select())
        if current_tab == 1:  # 完整日志
            self.search_bar.toggle()
        elif current_tab == 2 and self.source_viewer:  # 脚本源码
            self.source_viewer.search_bar.toggle()

    def _show_error(self, msg):
        self.status_var.set("✗ 分析失败")
        messagebox.showerror("分析失败", msg, parent=self.top)

    def _set_text(self, widget, content):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, content)
        widget.config(state=tk.DISABLED)
