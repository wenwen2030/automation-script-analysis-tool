"""监控模式 GUI 面板：持续监控目录下的脚本日志，显示状态和结果"""

import time
import threading
import tkinter as tk
import tkinter.ttk as ttk
import paramiko

from .. import theme
from ..config import POLL_INTERVAL, FINISH_PATTERN, IGNORE_FILES
from ..core.monitor import monitor, find_new_log
from ..utils import show_popup


class MonitorPanel:
    """监控模式面板：持续监控，显示已运行时间和检测到的脚本结果"""

    def __init__(self, host, user, password, monitor_dir, popup_enabled):
        self.host = host
        self.user = user
        self.password = password
        self.monitor_dir = monitor_dir
        self.popup_enabled = popup_enabled

        self.stop_event = threading.Event()
        self.worker_thread = None
        self.start_time = None
        self.timer_id = None
        self.results = []

        # 返回标记
        self.go_back = False

        self._build_gui()

    def _build_gui(self):
        self.root = tk.Tk()
        self.root.title("监控模式")
        self.root.geometry("900x600")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        theme.apply(self.root)

        # 顶部状态栏
        header = ttk.Frame(self.root, padding=(15, 10))
        header.pack(fill="x")

        self.status_var = tk.StringVar(value="● 就绪")
        ttk.Label(header, textvariable=self.status_var,
                  font=("Segoe UI", 11, "bold")).pack(side="left")

        self.time_var = tk.StringVar(value="已运行: 0:00:00")
        ttk.Label(header, textvariable=self.time_var,
                  foreground="#0078d4", font=("Segoe UI", 10)).pack(side="left", padx=20)

        self.current_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.current_var,
                  foreground="#888888", font=("Segoe UI", 9)).pack(side="left", padx=10)

        # 底部按钮
        ctrl_frame = ttk.Frame(self.root, padding=(15, 8))
        ctrl_frame.pack(side="bottom", fill="x")
        self.start_btn = ttk.Button(ctrl_frame, text="▶  开始监控", width=14,
                                    style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(ctrl_frame, text="■  停止监控", width=14,
                                   command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side="left", padx=5)
        self.back_btn = ttk.Button(ctrl_frame, text="←  返回登录", width=14,
                                   command=self._on_back)
        self.back_btn.pack(side="right", padx=5)

        # 主体：左侧结果列表 + 右侧日志
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(padx=12, pady=(0, 8), fill="both", expand=True)

        # 左侧：检测到的脚本结果
        left_frame = ttk.LabelFrame(paned, text="  检测到的脚本  ", padding=8)
        columns = ("script", "result", "time")
        self.result_tree = ttk.Treeview(left_frame, columns=columns, show="headings", height=15)
        self.result_tree.heading("script", text="脚本名")
        self.result_tree.heading("result", text="结果")
        self.result_tree.heading("time", text="时间")
        self.result_tree.column("script", width=180, minwidth=100)
        self.result_tree.column("result", width=60, minwidth=40, anchor="center")
        self.result_tree.column("time", width=70, minwidth=50, anchor="center")
        self.result_tree.tag_configure("pass", foreground="#1aaa55")
        self.result_tree.tag_configure("fail", foreground="#e53935")
        res_sb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.result_tree.yview)
        self.result_tree.config(yscrollcommand=res_sb.set)
        self.result_tree.pack(side="left", fill="both", expand=True)
        res_sb.pack(side="left", fill="y")

        self.stats_var = tk.StringVar(value="PASS: 0    FAIL: 0    总计: 0")
        ttk.Label(left_frame, textvariable=self.stats_var,
                  font=("Segoe UI", 9, "bold")).pack(pady=(8, 0))
        paned.add(left_frame, weight=1)

        # 右侧：实时日志
        right_frame = ttk.LabelFrame(paned, text="  监控日志  ", padding=8)
        self.log_text = tk.Text(
            right_frame, wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), state=tk.DISABLED,
            insertbackground="#d4d4d4",
            borderwidth=0, highlightthickness=0,
        )
        log_sb = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="left", fill="y")
        self.log_text.tag_configure("info", foreground="#d4d4d4")
        self.log_text.tag_configure("success", foreground="#6a9955")
        self.log_text.tag_configure("error", foreground="#f44747")
        self.log_text.tag_configure("highlight", foreground="#dcdcaa")
        paned.add(right_frame, weight=2)

        self.root.update_idletasks()
        theme.apply(self.root)

    def log(self, msg, tag="info"):
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _append)

    def _start(self):
        self.stop_event.clear()
        self.start_time = time.time()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("● 监控中...")
        self._start_timer()
        self.worker_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self.stop_event.set()
        self.status_var.set("○ 正在停止...")
        self.stop_btn.config(state=tk.DISABLED)

    def _start_timer(self):
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours, rem = divmod(elapsed, 3600)
            mins, secs = divmod(rem, 60)
            self.time_var.set(f"已运行: {hours}:{mins:02d}:{secs:02d}")
        self.timer_id = self.root.after(1000, self._start_timer)

    def _stop_timer(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

    def _monitor_worker(self):
        """后台监控线程"""
        finished_logs = set()
        self.log("=== 监控模式启动 ===", "highlight")
        self.log(f"服务器: {self.host}")
        self.log(f"监控目录: {self.monitor_dir}")
        self.log(f"每 {POLL_INTERVAL} 秒检查一次\n")

        while not self.stop_event.is_set():
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(self.host, username=self.user, password=self.password,
                               timeout=10, look_for_keys=False, allow_agent=False)

                log_file = find_new_log(client, finished_logs, self.monitor_dir)
                client.close()

                if not log_file:
                    self.root.after(0, lambda: self.current_var.set("等待新脚本启动..."))
                    self.log(f"  [{time.strftime('%H:%M:%S')}] 等待新的测试脚本启动...")
                    for _ in range(POLL_INTERVAL):
                        if self.stop_event.is_set():
                            break
                        time.sleep(1)
                    continue

                import os
                script_name = os.path.basename(log_file).replace(".txt", "")
                self.root.after(0, lambda n=script_name: self.current_var.set(f"正在监控: {n}"))
                self.log(f"\n发现新日志: {log_file}", "highlight")

                result = monitor(log_file, self.host, self.user, self.password,
                                 stop_event=self.stop_event, log_fn=self.log)

                if result:
                    if self.popup_enabled:
                        show_popup(result)
                    finished_logs.add(log_file)
                    self._add_result(script_name, result)
                    self.log(f"\n继续监控下一个脚本...\n")
                elif self.stop_event.is_set():
                    break
                else:
                    break

            except Exception as e:
                if self.stop_event.is_set():
                    break
                self.log(f"  连接异常: {e}，10秒后重试...", "error")
                for _ in range(10):
                    if self.stop_event.is_set():
                        break
                    time.sleep(1)

        self.root.after(0, self._on_stopped)

    def _add_result(self, script_name, result):
        def _add():
            tag = "pass" if result.lower() == "pass" else "fail"
            self.result_tree.insert("", "end",
                                    values=(script_name, result.upper(), time.strftime("%H:%M")),
                                    tags=(tag,))
            self.results.append((script_name, result))
            self._update_stats()
        self.root.after(0, _add)

    def _update_stats(self):
        pass_count = sum(1 for _, r in self.results if r.lower() == "pass")
        fail_count = sum(1 for _, r in self.results if r.lower() != "pass")
        self.stats_var.set(f"PASS: {pass_count}    FAIL: {fail_count}    总计: {len(self.results)}")

    def _on_stopped(self):
        self._stop_timer()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("⏹ 已停止")
        self.current_var.set("")

    def _on_back(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_event.set()
            self.worker_thread.join(timeout=3)
        self.go_back = True
        self._stop_timer()
        self.root.destroy()

    def _on_close(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_event.set()
        self._stop_timer()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
