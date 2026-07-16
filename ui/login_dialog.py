"""登录对话框 GUI（sv-ttk 主题）"""

import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from .. import theme
from ..config import (
    DEFAULT_HOST, DEFAULT_USER, DEFAULT_PASS, DEFAULT_DIR,
    DEFAULT_AUTOMATION_CMD, DEFAULT_DUT_NAME,
    DEFAULT_DUT_IP, DEFAULT_DUT_USER, DEFAULT_DUT_PASS,
    MAX_RETRY,
)


def _get_settings_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "login_settings.json")


def _load_settings():
    path = _get_settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_settings(data):
    path = _get_settings_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class LoginDialog:
    """SSH 登录参数输入对话框，支持监控模式和批量跑模式切换"""

    FIELD_LABELS = {
        "host": "SSH_HOST",
        "user": "SSH_USER",
        "password": "SSH_PASS",
        "monitor_dir": "Monitor_Dir",
    }

    def __init__(self, master, initial_scripts=None):
        self.top = tk.Toplevel(master)
        self.top.title("测试脚本工具")
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._result = None

        self._set_icon(self.top)

        saved = _load_settings()

        # 主题已经在 show_login 里应用过，这里只确保设置同步
        theme.set_current(saved.get("theme", "light"))

        # 主容器
        container = ttk.Frame(self.top, padding=15)
        container.pack(fill="both", expand=True)

        # === 顶部标题 ===
        title_frame = ttk.Frame(container)
        title_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(title_frame, text="测试脚本工具", font=("Segoe UI", 14, "bold")).pack(side="left")

        # 主题切换
        self.theme_var = tk.StringVar(value=theme.get_current())
        theme_frame = ttk.Frame(title_frame)
        theme_frame.pack(side="right")
        ttk.Label(theme_frame, text="主题:").pack(side="left", padx=(0, 5))
        ttk.Combobox(theme_frame, textvariable=self.theme_var,
                     values=["light", "dark"], width=6, state="readonly"
                     ).pack(side="left")
        self.theme_var.trace_add("write", self._on_theme_change)

        # === 公共字段 ===
        form_frame = ttk.LabelFrame(container, text="服务器连接", padding=10)
        form_frame.pack(fill="x", pady=(0, 8))

        self.host_var = tk.StringVar(value=saved.get("host", DEFAULT_HOST))
        self.user_var = tk.StringVar(value=saved.get("user", DEFAULT_USER))
        self.pass_var = tk.StringVar(value=saved.get("password", DEFAULT_PASS))
        self.dir_var = tk.StringVar(value=saved.get("monitor_dir", DEFAULT_DIR))

        self._add_field(form_frame, 0, "SSH_HOST:", self.host_var)
        self._add_field(form_frame, 1, "SSH_USER:", self.user_var)
        self._add_field(form_frame, 2, "SSH_PASS:", self.pass_var, show="*")
        self._add_field(form_frame, 3, "Monitor_Dir:", self.dir_var)
        form_frame.columnconfigure(1, weight=1)

        # === 模式选择 ===
        mode_frame = ttk.Frame(container)
        mode_frame.pack(fill="x", pady=8)
        ttk.Label(mode_frame, text="运行模式:").pack(side="left", padx=(0, 10))
        self.mode_var = tk.StringVar(value="monitor")
        ttk.Radiobutton(mode_frame, text="监控模式", variable=self.mode_var,
                        value="monitor", command=self._toggle_batch).pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="运行/分析脚本模式", variable=self.mode_var,
                        value="batch", command=self._toggle_batch).pack(side="left", padx=10)

        self.popup_var = tk.BooleanVar(value=True)

        # === 批量跑配置区 ===
        self.batch_frame = ttk.LabelFrame(container, text="批量跑配置", padding=10)
        self.batch_frame.pack(fill="both", expand=True, pady=(0, 8))

        self.dut_var = tk.StringVar(value=saved.get("dut_name", DEFAULT_DUT_NAME))
        self.dut_user_var = tk.StringVar(value=saved.get("dut_user", DEFAULT_DUT_USER))
        self.dut_pass_var = tk.StringVar(value=saved.get("dut_pass", DEFAULT_DUT_PASS))
        self.cmd_var = tk.StringVar(value=saved.get("automation_cmd", DEFAULT_AUTOMATION_CMD))
        self.retry_var = tk.IntVar(value=int(saved.get("max_retry", MAX_RETRY)))

        self._add_field(self.batch_frame, 0, "DB 名称:", self.dut_var)

        # === 拓扑模式切换: 单机 / 组网 ===
        topo_frame = ttk.Frame(self.batch_frame)
        topo_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=4)
        ttk.Label(topo_frame, text="拓扑模式:").pack(side="left", padx=(0, 10))
        self._topo_mode = tk.StringVar(value=saved.get("topo_mode", "single"))
        ttk.Radiobutton(topo_frame, text="单机", variable=self._topo_mode,
                        value="single", command=self._toggle_topo).pack(side="left", padx=5)
        ttk.Radiobutton(topo_frame, text="组网", variable=self._topo_mode,
                        value="multi", command=self._toggle_topo).pack(side="left", padx=5)

        # --- 单机模式: 单个DUT IP输入框 ---
        self._single_frame = ttk.Frame(self.batch_frame)
        self.dut_ip_var = tk.StringVar(value=saved.get("dut_ip", DEFAULT_DUT_IP))
        ttk.Label(self._single_frame, text="DUT IP:").grid(row=0, column=0, sticky="e", padx=5, pady=4)
        ttk.Entry(self._single_frame, textvariable=self.dut_ip_var).grid(row=0, column=1, sticky="ew", padx=5, pady=4)
        self._single_frame.columnconfigure(1, weight=1)

        # --- 组网模式: DUT设备列表 ---
        self._multi_frame = ttk.Frame(self.batch_frame)

        dut_list_label = ttk.Label(self._multi_frame, text="DUT 列表:")
        dut_list_label.grid(row=0, column=0, sticky="ne", padx=5, pady=4)

        dut_list_container = ttk.Frame(self._multi_frame)
        dut_list_container.grid(row=0, column=1, sticky="ew", padx=5, pady=4)

        self.dut_listbox = tk.Listbox(dut_list_container, height=4, width=40,
                                       font=("Consolas", 9))
        self.dut_listbox.pack(side="left", fill="both", expand=True)
        dut_sb = ttk.Scrollbar(dut_list_container, orient=tk.VERTICAL,
                                command=self.dut_listbox.yview)
        dut_sb.pack(side="left", fill="y")
        self.dut_listbox.config(yscrollcommand=dut_sb.set)

        dut_btn_frame = ttk.Frame(dut_list_container)
        dut_btn_frame.pack(side="left", padx=(8, 0))
        ttk.Button(dut_btn_frame, text="添加", width=6,
                   command=self._add_dut).pack(pady=2)
        ttk.Button(dut_btn_frame, text="删除", width=6,
                   command=self._remove_dut).pack(pady=2)

        self._multi_frame.columnconfigure(1, weight=1)

        # 加载已保存的DUT列表
        self._dut_devices = saved.get("dut_devices", [])
        if not self._dut_devices and saved.get("dut_ip"):
            self._dut_devices = [{"role": "DUT1", "ip": saved["dut_ip"]}]
        self._refresh_dut_listbox()

        # 初始显示对应模式
        self._toggle_topo()

        self._add_field(self.batch_frame, 3, "DUT 用户:", self.dut_user_var)
        self._add_field(self.batch_frame, 4, "DUT 密码:", self.dut_pass_var, show="*")
        self._add_field(self.batch_frame, 5, "执行命令:", self.cmd_var)

        # 重试次数行
        ttk.Label(self.batch_frame, text="失败重试次数:").grid(row=6, column=0, sticky="e", padx=5, pady=4)
        retry_row = ttk.Frame(self.batch_frame)
        retry_row.grid(row=6, column=1, sticky="w", pady=4)
        ttk.Spinbox(retry_row, from_=1, to=10, width=5,
                    textvariable=self.retry_var).pack(side="left")
        ttk.Label(retry_row, text="（连续 N 次都 fail 才算 fail）",
                  foreground="gray").pack(side="left", padx=8)

        # 飞书表格链接(可选,PASS时自动填写结果) — 不保存,每次手动填
        self.feishu_link_var = tk.StringVar(value="")
        ttk.Label(self.batch_frame, text="飞书表格:").grid(row=7, column=0, sticky="e", padx=5, pady=4)
        feishu_row = ttk.Frame(self.batch_frame)
        feishu_row.grid(row=7, column=1, sticky="ew", pady=4)
        ttk.Entry(feishu_row, textvariable=self.feishu_link_var,
                  font=("Consolas", 9)).pack(side="left", fill="x", expand=True)
        ttk.Label(feishu_row, text="(可选,PASS自动填写)",
                  foreground="gray").pack(side="left", padx=4)

        self.batch_frame.columnconfigure(1, weight=1)

        # 返回登录时恢复模式
        if initial_scripts:
            self.mode_var.set("batch")

        self._toggle_batch()

        # === 底部按钮 ===
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_frame, text="取消", width=12,
                   command=self._on_cancel).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="开始", width=12, style="Accent.TButton",
                   command=self._on_connect).pack(side="right", padx=4)

        # 构建完成后再强制 apply 一次，确保所有 ttk 控件样式刷新
        self.top.update_idletasks()
        theme.apply(self.top)

    def _add_field(self, parent, row, label, var, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=4)
        kwargs = {"textvariable": var}
        if show:
            kwargs["show"] = show
        entry = ttk.Entry(parent, **kwargs)
        entry.grid(row=row, column=1, sticky="ew", padx=5, pady=4)

    def _on_theme_change(self, *_):
        new_theme = self.theme_var.get()
        theme.set_current(new_theme)
        theme.apply(self.top)

    @staticmethod
    def _set_icon(window):
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(os.path.dirname(sys.executable), "app_icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                window.iconbitmap(icon_path)
            except Exception:
                pass

    @staticmethod
    def _parse_feishu_link(link):
        """从飞书表格链接中解析出spreadsheet_token和sheet_id

        支持格式:
            https://xxx.feishu.cn/sheets/TOKEN?sheet=SHEET_ID
            https://xxx.feishu.cn/sheets/TOKEN
        """
        import re
        if not link:
            return "", ""
        # 提取 spreadsheet_token
        m = re.search(r"/sheets/([A-Za-z0-9]+)", link)
        token = m.group(1) if m else ""
        # 提取 sheet_id (从?sheet=参数)
        m2 = re.search(r"[?&]sheet=([A-Za-z0-9]+)", link)
        sheet_id = m2.group(1) if m2 else ""
        return token, sheet_id

    def _toggle_batch(self):
        if self.mode_var.get() == "batch":
            self.batch_frame.pack(fill="both", expand=True, pady=(0, 8))
            self.top.geometry("")
        else:
            self.batch_frame.pack_forget()
            self.top.geometry("")

    def _toggle_topo(self):
        """切换单机/组网模式显示"""
        if self._topo_mode.get() == "single":
            self._multi_frame.grid_forget()
            self._single_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        else:
            self._single_frame.grid_forget()
            self._multi_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.top.geometry("")

    def _refresh_dut_listbox(self):
        """刷新DUT设备列表显示"""
        self.dut_listbox.delete(0, tk.END)
        for dev in self._dut_devices:
            self.dut_listbox.insert(tk.END, f"{dev['role']}  {dev['ip']}")

    def _add_dut(self):
        """弹窗添加一台DUT设备"""
        dialog = tk.Toplevel(self.top)
        dialog.title("添加 DUT")
        dialog.resizable(False, False)
        dialog.transient(self.top)
        dialog.grab_set()
        self._set_icon(dialog)

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="角色名:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        role_var = tk.StringVar(value=f"DUT{len(self._dut_devices) + 1}")
        ttk.Entry(frame, textvariable=role_var, width=20).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame, text="IP 地址:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        ip_var = tk.StringVar()
        ttk.Entry(frame, textvariable=ip_var, width=20).grid(row=1, column=1, padx=5, pady=5)

        def _confirm():
            role = role_var.get().strip()
            ip = ip_var.get().strip()
            if not role or not ip:
                return
            self._dut_devices.append({"role": role, "ip": ip})
            self._refresh_dut_listbox()
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_frame, text="确定", command=_confirm).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side="left", padx=5)

        dialog.wait_window()

    def _remove_dut(self):
        """删除选中的DUT设备"""
        sel = self.dut_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._dut_devices.pop(idx)
        self._refresh_dut_listbox()

    def validate_fields(self):
        empty = []
        values = {
            "host": self.host_var.get(),
            "user": self.user_var.get(),
            "password": self.pass_var.get(),
            "monitor_dir": self.dir_var.get(),
        }
        for key, val in values.items():
            if not val.strip():
                empty.append(self.FIELD_LABELS[key])
        return empty

    def _on_connect(self):
        empty = self.validate_fields()
        if empty:
            messagebox.showwarning("输入不完整", f"请填写以下字段：{', '.join(empty)}")
            return

        mode = self.mode_var.get()
        if mode == "batch":
            if not self.dut_var.get().strip():
                messagebox.showwarning("输入不完整", "请填写 DUT 名称")
                return

        self._result = {
            "host": self.host_var.get().strip(),
            "user": self.user_var.get().strip(),
            "password": self.pass_var.get(),
            "monitor_dir": self.dir_var.get().strip(),
            "mode": mode,
            "popup": self.popup_var.get(),
        }
        if mode == "batch":
            self._result["dut_name"] = self.dut_var.get().strip()
            # 根据拓扑模式构建设备列表
            if self._topo_mode.get() == "single":
                ip = self.dut_ip_var.get().strip()
                self._result["dut_devices"] = [{"role": "DUT1", "ip": ip}] if ip else []
                self._result["dut_ip"] = ip
            else:
                self._result["dut_devices"] = self._dut_devices
                self._result["dut_ip"] = self._dut_devices[0]["ip"] if self._dut_devices else ""
            self._result["dut_user"] = self.dut_user_var.get().strip()
            self._result["dut_pass"] = self.dut_pass_var.get()
            self._result["automation_cmd"] = self.cmd_var.get().strip()
            self._result["scripts"] = []
            try:
                self._result["max_retry"] = max(1, int(self.retry_var.get()))
            except (ValueError, tk.TclError):
                self._result["max_retry"] = MAX_RETRY
            # 解析飞书表格链接
            feishu_link = self.feishu_link_var.get().strip()
            fs_token, fs_sheet = self._parse_feishu_link(feishu_link)
            self._result["feishu_spreadsheet_token"] = fs_token
            self._result["feishu_sheet_id"] = fs_sheet

        try:
            saved_retry = max(1, int(self.retry_var.get()))
        except (ValueError, tk.TclError):
            saved_retry = MAX_RETRY

        _save_settings({
            "host": self.host_var.get().strip(),
            "user": self.user_var.get().strip(),
            "password": self.pass_var.get(),
            "monitor_dir": self.dir_var.get().strip(),
            "dut_name": self.dut_var.get().strip(),
            "topo_mode": self._topo_mode.get(),
            "dut_devices": self._dut_devices,
            "dut_ip": self.dut_ip_var.get().strip(),
            "dut_user": self.dut_user_var.get().strip(),
            "dut_pass": self.dut_pass_var.get(),
            "automation_cmd": self.cmd_var.get().strip(),
            "max_retry": saved_retry,
            "theme": theme.get_current(),
        })

        self.top.destroy()

    def _on_cancel(self):
        self._result = None
        self.top.destroy()

    @property
    def result(self):
        return self._result


def show_login(initial_scripts=None):
    root = tk.Tk()
    root.withdraw()
    # 先应用主题到根窗口，让 sv-ttk 资源（样式/字体）在创建 Toplevel 前就绪
    saved = _load_settings()
    theme.set_current(saved.get("theme", "light"))
    theme.apply(root)

    dlg = LoginDialog(root, initial_scripts=initial_scripts)

    # 启动后台版本检查
    from ..integrations.updater import check_update
    check_update(dlg.top)

    root.wait_window(dlg.top)
    result = dlg.result
    root.destroy()
    return result
