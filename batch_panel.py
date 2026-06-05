"""批量跑模式的 GUI 控制面板"""

import time
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox
import paramiko

from . import theme
from .analysis import AnalysisDialog
from .config import MAX_RETRY
from .monitor import monitor
from .ssh_terminal import SshTerminal, SshTerminalContainer
from .utils import show_popup


class BatchControlPanel:
    """批量跑模式的 GUI 控制面板，执行期间保持可交互"""

    def __init__(self, host, user, password, monitor_dir, popup_enabled,
                 automation_cmd, dut_name, initial_scripts,
                 dut_ip="", dut_user="admin", dut_pass="pica8", max_retry=MAX_RETRY):
        self.host = host
        self.user = user
        self.password = password
        self.monitor_dir = monitor_dir
        self.popup_enabled = popup_enabled
        self.automation_cmd = automation_cmd
        self.dut_name = dut_name
        self.dut_ip = dut_ip
        self.dut_user = dut_user
        self.dut_pass = dut_pass
        self.max_retry = max(1, int(max_retry))

        self.stop_event = threading.Event()
        self.worker_thread = None
        self.summary = []
        self.current_start_time = None
        self.timer_id = None
        self.current_script_name = None

        # 返回上一界面标记，由 __main__ 检测
        self.go_back = False
        # 关闭时当前的脚本列表快照（供返回登录界面后恢复）
        self.current_scripts = list(initial_scripts)

        self._build_gui(initial_scripts)

    def _build_gui(self, initial_scripts):
        self.root = tk.Tk()
        self.root.title("批量跑控制面板")
        self.root.geometry("1400x800")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_icon(self.root)

        # 应用主题（来自登录界面保存的设置）
        theme.apply(self.root)
        pal = theme.palette()

        # 顶部状态栏
        header = ttk.Frame(self.root, padding=(15, 10))
        header.pack(fill="x")

        self.status_var = tk.StringVar(value="● 就绪")
        status_label = ttk.Label(header, textvariable=self.status_var,
                                 font=("Segoe UI", 11, "bold"))
        status_label.pack(side="left")

        self.current_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.current_var,
                  foreground="#0078d4", font=("Segoe UI", 9)).pack(side="left", padx=15)

        # 主题切换 + 弹窗通知
        theme_frame = ttk.Frame(header)
        theme_frame.pack(side="right")

        self.popup_var = tk.BooleanVar(value=self.popup_enabled)
        ttk.Checkbutton(theme_frame, text="弹窗通知",
                        variable=self.popup_var,
                        command=self._on_popup_toggle).pack(side="left", padx=(0, 12))

        ttk.Label(theme_frame, text="主题:").pack(side="left", padx=(0, 4))
        self.theme_var = tk.StringVar(value=theme.get_current())
        ttk.Combobox(theme_frame, textvariable=self.theme_var,
                     values=["light", "dark"], width=6, state="readonly"
                     ).pack(side="left")
        self.theme_var.trace_add("write", self._on_theme_change)

        # === 底部固定控制按钮区（在 paned 之外，永远可见）===
        ctrl_frame = ttk.Frame(self.root, padding=(15, 8))
        ctrl_frame.pack(side="bottom", fill="x")
        self.start_btn = ttk.Button(ctrl_frame, text="▶  开始执行", width=14,
                                    style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(ctrl_frame, text="■  停止", width=12,
                                   command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side="left", padx=5)
        self.back_btn = ttk.Button(ctrl_frame, text="←  返回登录", width=14,
                                   command=self._on_back)
        self.back_btn.pack(side="right", padx=5)

        # === 主布局：左右分割 ===
        # 左侧：上=待执行脚本列表，下=执行结果
        # 右侧：Notebook（执行日志 / SSH 终端）
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(padx=12, pady=(0, 8), fill="both", expand=True)
        self.main_paned = main_paned

        # 设置整窗最小尺寸，避免拖太小让按钮被遮住
        self.root.minsize(900, 560)

        # ---- 左侧上下分割 ----
        left_paned = ttk.PanedWindow(main_paned, orient=tk.VERTICAL)

        # 左上：待执行脚本列表
        list_frame = ttk.LabelFrame(left_paned, text="  待执行脚本（可实时增删）  ", padding=8)

        lb_frame = ttk.Frame(list_frame)
        lb_frame.pack(fill="both", expand=True)
        self.script_listbox = tk.Listbox(
            lb_frame, height=10, selectmode=tk.SINGLE,
            bg=pal["bg"], fg=pal["fg"],
            selectbackground=pal["select_bg"], selectforeground=pal["select_fg"],
            borderwidth=1, relief="solid", highlightthickness=0,
            font=("Consolas", 9),
        )
        scrollbar = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=self.script_listbox.yview)
        self.script_listbox.config(yscrollcommand=scrollbar.set)
        self.script_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

        for s in initial_scripts:
            self.script_listbox.insert(tk.END, s)

        input_frame = ttk.Frame(list_frame)
        input_frame.pack(fill="x", pady=(8, 3))
        # 按钮列先 pack 在右边，固定宽度；输入框填充剩余
        btn_col = ttk.Frame(input_frame)
        btn_col.pack(side="right", padx=4)
        ttk.Button(btn_col, text="批量添加", width=10, command=self._add_scripts).pack(pady=1, fill="x")
        ttk.Button(btn_col, text="删除选中", width=10, command=self._del_script).pack(pady=1, fill="x")
        ttk.Button(btn_col, text="清空列表", width=10, command=self._clear_scripts).pack(pady=1, fill="x")
        self.script_input_text = tk.Text(
            input_frame, height=3,
            bg=pal["bg"], fg=pal["fg"],
            insertbackground=pal["fg"],
            borderwidth=1, relief="solid", highlightthickness=0,
            font=("Consolas", 9),
        )
        self.script_input_text.pack(side="left", padx=2, fill="both", expand=True)

        move_frame = ttk.Frame(list_frame)
        move_frame.pack(pady=4)
        ttk.Button(move_frame, text="↑ 上移", width=10, command=self._move_up).pack(side="left", padx=5)
        ttk.Button(move_frame, text="↓ 下移", width=10, command=self._move_down).pack(side="left", padx=5)

        left_paned.add(list_frame, weight=1)

        # 左下：执行结果面板
        result_frame = ttk.LabelFrame(left_paned, text="  执行结果  ", padding=8)

        tree_container = ttk.Frame(result_frame)
        tree_container.pack(fill="both", expand=True)

        columns = ("script", "result", "duration")
        self.result_tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=10)
        self.result_tree.heading("script", text="脚本名")
        self.result_tree.heading("result", text="结果")
        self.result_tree.heading("duration", text="耗时")
        self.result_tree.column("script", width=180, minwidth=100)
        self.result_tree.column("result", width=70, minwidth=50, anchor="center")
        self.result_tree.column("duration", width=70, minwidth=50, anchor="center")

        self.result_tree.tag_configure("pass", foreground="#1aaa55")
        self.result_tree.tag_configure("fail", foreground="#e53935")
        self.result_tree.tag_configure("running", foreground="#0078d4")
        self.result_tree.tag_configure("stopped", foreground="#888888")

        res_scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.result_tree.yview)
        self.result_tree.config(yscrollcommand=res_scrollbar.set)
        self.result_tree.pack(side="left", fill="both", expand=True)
        res_scrollbar.pack(side="left", fill="y")

        # 右键菜单：分析失败原因 / 复制脚本名
        self.result_menu = tk.Menu(self.result_tree, tearoff=0)
        self.result_menu.add_command(label="复制脚本名", command=self._copy_script_name)
        self.result_menu.add_command(label="分析失败原因...", command=self._analyze_selected)
        self.result_tree.bind("<Button-3>", self._show_result_menu)
        # 双击直接分析
        self.result_tree.bind("<Double-1>", lambda e: self._analyze_selected())

        self.stats_var = tk.StringVar(value="PASS: 0    FAIL: 0    总计: 0")
        stats_frame = ttk.Frame(result_frame)
        stats_frame.pack(pady=(8, 0), fill="x")
        ttk.Label(stats_frame, textvariable=self.stats_var,
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(stats_frame, text="清空结果", width=10,
                   command=self._clear_results).pack(side="right")

        self.running_item_id = None

        left_paned.add(result_frame, weight=1)

        main_paned.add(left_paned, weight=1)
        # ---- 右侧：Notebook（执行日志 + SSH 终端） ----
        right_frame = ttk.Frame(main_paned)

        self.bottom_nb = ttk.Notebook(right_frame)
        self.bottom_nb.pack(fill="both", expand=True, padx=4, pady=4)

        # 执行日志标签页
        log_tab = ttk.Frame(self.bottom_nb, padding=4)
        self.log_text = tk.Text(
            log_tab, wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), state=tk.DISABLED,
            insertbackground="#d4d4d4",
            borderwidth=0, highlightthickness=0,
        )
        log_scrollbar = ttk.Scrollbar(log_tab, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="left", fill="y")

        self.log_text.tag_configure("info", foreground="#d4d4d4")
        self.log_text.tag_configure("success", foreground="#6a9955")
        self.log_text.tag_configure("error", foreground="#f44747")
        self.log_text.tag_configure("highlight", foreground="#dcdcaa")

        self.bottom_nb.add(log_tab, text="  执行日志  ")

        # SSH 终端标签页（支持多开）
        self.ssh_terminal = SshTerminalContainer(
            self.bottom_nb,
            default_host=self.dut_ip,
            default_user=self.dut_user,
            default_pass=self.dut_pass,
        )
        self.bottom_nb.add(self.ssh_terminal, text="  SSH 终端  ")

        main_paned.add(right_frame, weight=3)

        # 构建完成后再强制 apply 一次，确保所有 ttk 控件样式刷新
        self.root.update_idletasks()
        theme.apply(self.root)

        # tag_configure 必须在 theme apply 之后，否则会被主题覆盖
        self.result_tree.tag_configure("pass", foreground="#1aaa55")
        self.result_tree.tag_configure("fail", foreground="#e53935")
        self.result_tree.tag_configure("running", foreground="#0078d4")
        self.result_tree.tag_configure("stopped", foreground="#888888")

        # 设置初始分割位置：左侧占 25%，右侧占 75%
        self.root.after(100, self._set_initial_sash)
        # 恢复上次的执行结果
        self._load_results()

    def _on_popup_toggle(self):
        self.popup_enabled = self.popup_var.get()

    def _on_theme_change(self, *_):
        new_theme = self.theme_var.get()
        theme.set_current(new_theme)
        theme.apply(self.root)
        pal = theme.palette()
        for widget in (self.script_listbox, self.script_input_text):
            widget.configure(
                bg=pal["bg"], fg=pal["fg"],
                selectbackground=pal["select_bg"],
                selectforeground=pal["select_fg"],
            )

    def _set_initial_sash(self):
        """设置左右分割的初始位置（左侧 30%）"""
        try:
            total_width = self.root.winfo_width()
            if total_width > 100:
                # 左侧占 30%
                self.main_paned.sashpos(0, int(total_width * 0.25))
        except Exception:
            pass

    def _show_result_menu(self, event):
        """右键执行结果项时弹出菜单"""
        item = self.result_tree.identify_row(event.y)
        if not item:
            return
        self.result_tree.selection_set(item)
        try:
            self.result_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.result_menu.grab_release()

    def _copy_script_name(self):
        """复制选中行的脚本名到剪贴板"""
        sel = self.result_tree.selection()
        if not sel:
            return
        script_name = self.result_tree.set(sel[0], "script")
        if script_name:
            self.root.clipboard_clear()
            self.root.clipboard_append(script_name)

    def _analyze_selected(self):
        """分析当前选中行对应的脚本日志"""
        sel = self.result_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在执行结果中选中一行", parent=self.root)
            return
        item = sel[0]
        script_name = self.result_tree.set(item, "script")
        if not script_name:
            return
        # 弹出分析窗口（异步加载日志）
        AnalysisDialog(
            parent=self.root,
            host=self.host,
            user=self.user,
            password=self.password,
            monitor_dir=self.monitor_dir,
            script_name=script_name,
        )

    # ---- 列表操作 ----

    def log(self, msg, tag="info"):
        """向日志面板追加一行文本（线程安全）"""
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _append)

    def _add_scripts(self):
        raw = self.script_input_text.get("1.0", tk.END)
        existing = set(self.script_listbox.get(0, tk.END))
        for line in raw.splitlines():
            name = line.strip()
            if name and name not in existing:
                self.script_listbox.insert(tk.END, name)
                existing.add(name)
        self.script_input_text.delete("1.0", tk.END)

    def _del_script(self):
        sel = self.script_listbox.curselection()
        if sel:
            self.script_listbox.delete(sel[0])

    def _clear_scripts(self):
        self.script_listbox.delete(0, tk.END)

    def _move_up(self):
        sel = self.script_listbox.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            text = self.script_listbox.get(idx)
            self.script_listbox.delete(idx)
            self.script_listbox.insert(idx - 1, text)
            self.script_listbox.selection_set(idx - 1)

    def _move_down(self):
        sel = self.script_listbox.curselection()
        if sel and sel[0] < self.script_listbox.size() - 1:
            idx = sel[0]
            text = self.script_listbox.get(idx)
            self.script_listbox.delete(idx)
            self.script_listbox.insert(idx + 1, text)
            self.script_listbox.selection_set(idx + 1)

    # ---- 执行控制 ----

    def _start(self):
        self.stop_event.clear()
        self.summary = []
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("● 执行中...")
        self.worker_thread = threading.Thread(target=self._batch_worker, daemon=True)
        self.worker_thread.start()
        self._poll_worker()

    def _stop(self):
        self.stop_event.set()
        self.status_var.set("○ 正在停止...")
        self.stop_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._kill_remote, daemon=True).start()

    def _kill_remote(self):
        """停止按钮触发：kill 远程进程 + 恢复交换机"""
        script_name = self.current_script_name
        self._cleanup_and_restore(script_name)

    def _cleanup_and_restore(self, script_name=None):
        """清理远程进程并恢复交换机初始配置（可在任意线程调用）"""
        # 1. 终止远程服务器上的脚本进程
        if script_name:
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(self.host, username=self.user, password=self.password, timeout=10)
                kill_cmd = f"pkill -f '{self.dut_name} {script_name}'"
                client.exec_command(kill_cmd)
                time.sleep(1)
                kill_cmd2 = f"pkill -9 -f '{self.dut_name} {script_name}'"
                client.exec_command(kill_cmd2)
                client.close()
                self.log(f"已终止远程进程: {script_name}", "highlight")
            except Exception as e:
                self.log(f"终止远程进程失败: {e}", "error")

        # 2. SSH 到交换机恢复初始配置
        if not self.dut_ip:
            self.log("未配置 DUT IP，跳过交换机配置恢复")
            return

        try:
            self.log(f"正在连接交换机 {self.dut_ip} 恢复配置...", "highlight")
            dut_client = paramiko.SSHClient()
            dut_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            dut_client.connect(self.dut_ip, username=self.dut_user, password=self.dut_pass, timeout=15,
                               look_for_keys=False, allow_agent=False)
            shell = dut_client.invoke_shell(width=200, height=50)
            time.sleep(1)
            if shell.recv_ready():
                shell.recv(65535)

            shell.send("configure\n")
            time.sleep(2)
            shell.send("load override /cftmp/pica_startup.boot\n")
            time.sleep(5)
            shell.send("commit\n")
            time.sleep(10)

            output = b""
            while shell.recv_ready():
                output += shell.recv(65535)
            self.log(f"交换机输出: {output.decode('utf-8', errors='replace')}")

            shell.send("exit\n")
            time.sleep(1)
            dut_client.close()
            self.log(f"交换机 {self.dut_ip} 配置已恢复", "success")
        except Exception as e:
            self.log(f"交换机配置恢复失败: {e}", "error")

    def _poll_worker(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.root.after(500, self._poll_worker)
        else:
            self._stop_timer()
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            if self.stop_event.is_set():
                self.status_var.set("⏹ 已停止")
            else:
                self.status_var.set("✓ 全部完成")
            self._log_summary()

    def _take_next_script(self):
        result = []
        event = threading.Event()
        def _pop():
            if self.script_listbox.size() > 0:
                name = self.script_listbox.get(0)
                self.script_listbox.delete(0)
                result.append(name)
            event.set()
        self.root.after(0, _pop)
        event.wait(timeout=5)
        return result[0] if result else None

    def _update_status(self, text):
        self.root.after(0, lambda: self.current_var.set(text))

    def _log_summary(self):
        """将汇总信息输出到日志面板"""
        self.log(f"\n{'='*50}", "highlight")
        self.log("批量执行汇总", "highlight")
        self.log(f"{'='*50}", "highlight")
        pass_count = fail_count = 0
        for i, (name, result, attempts) in enumerate(self.summary, 1):
            tag = "success" if result == "PASS" else "error"
            self.log(f"  {i}. {name:<30} {result:<8} (第{attempts}次)", tag)
            if result == "PASS":
                pass_count += 1
            else:
                fail_count += 1
        self.log(f"{'='*50}", "highlight")
        self.log(f"总计: {len(self.summary)} 个脚本，PASS: {pass_count}，其他: {fail_count}", "highlight")

    # ---- 结果面板 ----

    def _add_running_item(self, script_name):
        event = threading.Event()
        def _add():
            item_id = self.result_tree.insert("", "end", values=(script_name, "运行中...", "0:00"), tags=("running",))
            self.running_item_id = item_id
            self.result_tree.see(item_id)
            self.current_start_time = time.time()
            self._start_timer()
            event.set()
        self.root.after(0, _add)
        event.wait(timeout=5)

    def _start_timer(self):
        if self.running_item_id and self.current_start_time:
            elapsed = int(time.time() - self.current_start_time)
            mins, secs = divmod(elapsed, 60)
            hours, mins = divmod(mins, 60)
            time_str = f"{hours}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins}:{secs:02d}"
            try:
                self.result_tree.set(self.running_item_id, "duration", time_str)
            except tk.TclError:
                pass
        self.timer_id = self.root.after(1000, self._start_timer)

    def _stop_timer(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

    def _update_result_item(self, result_text):
        def _update():
            if self.running_item_id:
                self._stop_timer()
                elapsed = int(time.time() - self.current_start_time) if self.current_start_time else 0
                mins, secs = divmod(elapsed, 60)
                hours, mins = divmod(mins, 60)
                time_str = f"{hours}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins}:{secs:02d}"
                tag = "pass" if result_text.upper() == "PASS" else "fail" if result_text.upper() in ("FAIL", "ERRSCRIPT") else "stopped"
                self.result_tree.item(self.running_item_id, values=(
                    self.result_tree.set(self.running_item_id, "script"),
                    result_text.upper(), time_str
                ), tags=(tag,))
                self.running_item_id = None
                self.current_start_time = None
                self._update_stats()
        self.root.after(0, _update)

    def _update_stats(self):
        pass_count = fail_count = total = 0
        for item_id in self.result_tree.get_children():
            result = self.result_tree.set(item_id, "result")
            if result == "PASS":
                pass_count += 1; total += 1
            elif result in ("FAIL", "ERRSCRIPT", "UNKNOWN", "中断"):
                fail_count += 1; total += 1
        self.stats_var.set(f"PASS: {pass_count}    FAIL: {fail_count}    总计: {total}")

    def _clear_results(self):
        """清空执行结果"""
        self.result_tree.delete(*self.result_tree.get_children())
        self.summary = []
        self._update_stats()

    # ---- 后台执行 ----

    def _batch_worker(self):
        self.log("=== 测试脚本工具 (批量跑模式) ===", "highlight")
        self.log(f"服务器: {self.host}")
        self.log(f"DUT: {self.dut_name}")
        self.log(f"失败重试: 最多 {self.max_retry} 次")

        idx = 0
        while not self.stop_event.is_set():
            script_name = self._take_next_script()
            if script_name is None:
                break

            idx += 1
            self._update_status(f"正在执行: {script_name}")
            self._add_running_item(script_name)
            self.log(f"\n{'='*50}", "highlight")
            self.log(f"[{idx}] {script_name}", "highlight")
            self.log(f"{'='*50}", "highlight")

            final_result = None
            attempts = 0

            for attempt in range(1, self.max_retry + 1):
                if self.stop_event.is_set():
                    self._update_result_item("中断")
                    self.summary.append((script_name, "中断", attempt))
                    return

                attempts = attempt
                self.log(f"--- 第 {attempt}/{self.max_retry} 次执行 ---")

                try:
                    result = self._run_one(script_name)
                except Exception as e:
                    self.log(f"  执行异常: {e}", "error")
                    result = "fail"

                if result is None:
                    self._update_result_item("中断")
                    self.summary.append((script_name, "中断", attempts))
                    return

                if result.lower() == "pass":
                    final_result = result
                    if self.popup_enabled:
                        show_popup(result)
                    break
                else:
                    # 异常/卡住/失败时，先清理远程进程并恢复交换机环境
                    if result.lower() in ("stall", "errscript"):
                        self.log(f"  脚本异常({result.upper()})，正在清理环境...", "error")
                        self._cleanup_and_restore(script_name)

                    if attempt < self.max_retry:
                        self.log(f"  结果: {result.upper()}，将重试...", "error")
                    else:
                        self.log(f"  结果: {result.upper()}，已达最大重试次数，跳过", "error")
                        final_result = result
                        if self.popup_enabled:
                            show_popup(result)

            self._update_result_item(final_result.upper() if final_result else "UNKNOWN")
            self.summary.append((script_name, final_result.upper() if final_result else "UNKNOWN", attempts))

        self._update_status("")
        self._stop_timer()

    def _run_one(self, script_name):
        self.current_script_name = script_name
        full_cmd = f"cd {self.monitor_dir} && {self.automation_cmd} {self.dut_name} {script_name}"

        log_file = f"{self.monitor_dir.rstrip('/')}/{script_name}.txt"

        # 通过终端前台执行脚本，让用户能实时看到输出
        # 先确保终端连接到服务器
        result_holder = []
        done_event = threading.Event()
        def _get_term():
            try:
                t = self.ssh_terminal.get_or_create_terminal_for(
                    self.host, self.user, self.password, port=22,
                    title=f"服务器 ({self.host})")
                result_holder.append(t)
            finally:
                done_event.set()
        self.root.after(0, _get_term)
        done_event.wait(timeout=5)

        if not result_holder:
            self.log("  无法创建终端", "error")
            self.current_script_name = None
            return "fail"
        term = result_holder[0]

        if not term.wait_connected(timeout=15):
            self.log("  终端连接服务器失败", "error")
            self.current_script_name = None
            return "fail"

        # 切换到终端标签页
        try:
            self.root.after(0, lambda: self.bottom_nb.select(self.ssh_terminal))
        except Exception:
            pass

        # 等 shell ready
        time.sleep(0.5)

        # 前台执行脚本（终端能实时看到输出）
        self.log(f"  执行: {full_cmd}")
        term.send_command(full_cmd)

        # 等一会让脚本启动并创建日志文件
        time.sleep(3)

        # 用独立 SSH 连接监控日志文件等待结果
        result = monitor(log_file, self.host, self.user, self.password,
                         stop_event=self.stop_event, log_fn=self.log,
                         process_keyword=f"{self.dut_name} {script_name}")
        self.current_script_name = None
        return result

    def _on_back(self):
        """返回登录界面：如果有任务在跑则确认，停止后退出当前面板"""
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno("确认返回", "脚本正在执行中，返回登录界面将停止执行，确定吗？"):
                return
            self.stop_event.set()
            # 等待线程退出，最多等 2 秒
            self.worker_thread.join(timeout=2)
        self.go_back = True
        # 保存当前脚本列表快照
        self.current_scripts = list(self.script_listbox.get(0, tk.END))
        # 保存执行结果
        self._save_results()
        self._stop_timer()
        try:
            if hasattr(self, "ssh_terminal"):
                self.ssh_terminal.disconnect_all()
        except Exception:
            pass
        self.root.destroy()

    def _save_results(self):
        """保存执行结果到本地文件"""
        import json as _json
        results = []
        for item_id in self.result_tree.get_children():
            script = self.result_tree.set(item_id, "script")
            result = self.result_tree.set(item_id, "result")
            duration = self.result_tree.set(item_id, "duration")
            results.append({"script": script, "result": result, "duration": duration})
        try:
            import os as _os
            path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "last_results.json")
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(results, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_results(self):
        """恢复上次保存的执行结果"""
        import json as _json
        import os as _os
        try:
            path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "last_results.json")
            if not _os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                results = _json.load(f)
            for r in results:
                tag = "pass" if r["result"] == "PASS" else "fail" if r["result"] in ("FAIL", "ERRSCR", "ERRSCRIPT") else "stopped"
                self.result_tree.insert("", "end",
                                        values=(r["script"], r["result"], r["duration"]),
                                        tags=(tag,))
            self._update_stats()
        except Exception:
            pass

    def _on_close(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno("确认退出", "脚本正在执行中，确定要退出吗？"):
                return
            self.stop_event.set()
        self._stop_timer()
        # 先断开所有终端连接并等待线程退出
        try:
            if hasattr(self, "ssh_terminal"):
                self.ssh_terminal.disconnect_all()
        except Exception:
            pass
        # 等待 worker 线程退出
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)
        # 短暂等待让后台线程完全退出，避免 GC 在错误线程回收 Tk 变量
        import time
        time.sleep(0.2)
        self.root.destroy()

    def run(self):
        self.root.mainloop()

    @staticmethod
    def _set_icon(window):
        import os, sys
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(os.path.dirname(sys.executable), "app_icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                window.iconbitmap(icon_path)
            except Exception:
                pass
