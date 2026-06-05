"""嵌入式 SSH 终端组件（基于 pyte，带渲染节流防卡死）"""
import json, os, queue, re, socket, sys, threading, time
import tkinter as tk, tkinter.ttk as ttk
try:
    import paramiko
except ImportError:
    paramiko = None
try:
    import pyte
except ImportError:
    pyte = None

def _settings_path():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "ssh_terminal_settings.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssh_terminal_settings.json")

def _load_terminal_settings():
    p = _settings_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def _save_terminal_settings(data):
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

COLS, ROWS, HISTORY_LINES, REFRESH_INTERVAL = 120, 40, 20000, 100
KEY_MAP = {"Return":"\r","BackSpace":"\x08","Tab":"\t","Escape":"\x1b",
    "Up":"\x1b[A","Down":"\x1b[B","Right":"\x1b[C","Left":"\x1b[D",
    "Home":"\x1b[H","End":"\x1b[F","Delete":"\x1b[3~","Insert":"\x1b[2~",
    "F1":"\x1bOP","F2":"\x1bOQ","F3":"\x1bOR","F4":"\x1bOS"}
PYTE_COLORS = {"black":"#000000","red":"#cd3131","green":"#0dbc79",
    "yellow":"#e5e510","blue":"#2472c8","magenta":"#bc3fbc",
    "cyan":"#11a8cd","white":"#e5e5e5","brightblack":"#666666",
    "brightred":"#f14c4c","brightgreen":"#23d18b","brightyellow":"#f5f543",
    "brightblue":"#3b8eea","brightmagenta":"#d670d6","brightcyan":"#29b8db",
    "brightwhite":"#e5e5e5","default":"#d4d4d4"}


class SshTerminal(ttk.Frame):
    def __init__(self, parent, default_host="", default_user="admin",
                 default_pass="pica8", default_port=22, on_log=None):
        super().__init__(parent)
        self.on_log = on_log or (lambda msg, tag="info": None)
        self.client = self.shell = self.tn = None
        self.reader_thread = None
        self.connected = False
        self._stop_reader = threading.Event()
        if pyte:
            self.screen = pyte.HistoryScreen(COLS, ROWS, history=HISTORY_LINES, ratio=0.5)
            self.screen.set_mode(pyte.modes.LNM)
            self.stream = pyte.Stream(self.screen)
        else:
            self.screen = self.stream = None
        self._inbuf = queue.Queue()
        self._last_render_time = 0
        self._last_screen_hash = ""
        saved = _load_terminal_settings()
        self._build_ui(saved.get("host") or default_host, saved.get("user") or default_user,
                       saved.get("password") or default_pass, saved.get("port") or default_port)
        self._schedule_refresh()

    def _build_ui(self, host, user, pwd, port):
        tb = ttk.Frame(self); tb.pack(side="top", fill="x", padx=2, pady=(2,1))
        ttk.Label(tb, text="协议:").pack(side="left")
        self.proto_var = tk.StringVar(value="SSH")
        ttk.Combobox(tb, textvariable=self.proto_var, values=["SSH","Telnet"], width=7, state="readonly").pack(side="left", padx=(2,6))
        ttk.Label(tb, text="主机:").pack(side="left")
        self.host_var = tk.StringVar(value=host)
        ttk.Entry(tb, textvariable=self.host_var, width=14).pack(side="left", padx=2)
        ttk.Label(tb, text="用户:").pack(side="left", padx=(6,0))
        self.user_var = tk.StringVar(value=user)
        ttk.Entry(tb, textvariable=self.user_var, width=10).pack(side="left", padx=2)
        ttk.Label(tb, text="密码:").pack(side="left", padx=(6,0))
        self.pass_var = tk.StringVar(value=pwd)
        ttk.Entry(tb, textvariable=self.pass_var, width=10, show="*").pack(side="left", padx=2)
        ttk.Label(tb, text="端口:").pack(side="left", padx=(6,0))
        self.port_var = tk.IntVar(value=port)
        ttk.Entry(tb, textvariable=self.port_var, width=5).pack(side="left", padx=2)
        self.connect_btn = ttk.Button(tb, text="连接", width=8, style="Accent.TButton", command=self.toggle_connection)
        self.connect_btn.pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="● 未连接")
        self.status_label = ttk.Label(tb, textvariable=self.status_var, foreground="#888888")
        self.status_label.pack(side="left", padx=4)
        ttk.Button(tb, text="清屏", width=6, command=self.clear).pack(side="right", padx=2)
        sf = ttk.Frame(self); sf.pack(side="top", fill="both", expand=True, padx=2, pady=(1,2))
        self.text = tk.Text(sf, wrap=tk.NONE, bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4",
                            font=("Consolas",10), borderwidth=0, highlightthickness=0,
                            spacing1=0, spacing3=0, cursor="xterm", width=COLS, height=ROWS, undo=False, insertwidth=2, insertontime=600, insertofftime=300)
        vs = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=self.text.yview)
        self.text.config(yscrollcommand=vs.set)
        self.text.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns")
        sf.rowconfigure(0, weight=1); sf.columnconfigure(0, weight=1)
        for n, c in PYTE_COLORS.items():
            self.text.tag_configure(f"fg_{n}", foreground=c)
            self.text.tag_configure(f"bg_{n}", background=c)
        self.text.tag_configure("bold", font=("Consolas",10,"bold"))
        self.text.tag_configure("reverse", background="#d4d4d4", foreground="#1e1e1e")
        self.text.tag_configure("cursor_pos", background="#5a9e5a", foreground="#000000")
        self.text.bind("<Key>", self._on_key)
        self.text.bind("<Control-Key>", self._on_ctrl_key)
        self.text.bind("<Prior>", lambda e: (self.text.yview_scroll(-1,"pages"), "break")[-1])
        self.text.bind("<Next>", lambda e: (self.text.yview_scroll(1,"pages"), "break")[-1])
        # 屏幕区标记（LEFT gravity：在它之前插入历史时标记不移动）
        self.text.mark_set("screen_start", "1.0")
        self.text.mark_gravity("screen_start", tk.RIGHT)
        self.menu = tk.Menu(self.text, tearoff=0)
        self.menu.add_command(label="复制", command=self._copy)
        self.menu.add_command(label="粘贴", command=self._paste)
        self.menu.add_separator()
        self.menu.add_command(label="清屏", command=self.clear)
        # 初始化屏幕区域标记
        # screen_start: LEFT gravity（在它之前插入历史时，标记不移动）
        self.text.mark_set("screen_start", "1.0")
        self.text.mark_gravity("screen_start", tk.RIGHT)
        self._screen_mark = "screen_start"
        self.text.bind("<Button-3>", lambda e: (self.menu.tk_popup(e.x_root, e.y_root), self.menu.grab_release()))

    def _on_key(self, event):
        if not self.connected: return "break"
        ks = event.keysym
        if ks in ("Prior","Next"): return
        if ks in KEY_MAP: self._send(KEY_MAP[ks]); return "break"
        if event.char and event.char.isprintable(): self._send(event.char); return "break"
        return "break"

    def _on_ctrl_key(self, event):
        if not self.connected: return "break"
        ks = event.keysym.lower()
        if ks == "c":
            try: self.text.selection_get(); self._copy()
            except tk.TclError: self._send("\x03")
            return "break"
        if ks == "v": self._paste(); return "break"
        if len(ks)==1 and "a"<=ks<="z": self._send(chr(ord(ks)-ord("a")+1)); return "break"
        return "break"

    def _send(self, data):
        try:
            if isinstance(data, str): data = data.encode("utf-8", errors="replace")
            if self.shell: self.shell.send(data)
            elif self.tn: self.tn.sendall(data)
        except: pass

    def _copy(self):
        try: sel = self.text.selection_get(); self.clipboard_clear(); self.clipboard_append(sel)
        except: pass

    def _paste(self):
        try: d = self.clipboard_get(); self._send(d) if d else None
        except: pass

    def toggle_connection(self):
        self.disconnect() if self.connected else self.connect()

    def connect(self):
        if not pyte: return
        host = self.host_var.get().strip()
        if not host: return
        proto = self.proto_var.get()
        self.status_var.set("● 连接中..."); self.status_label.config(foreground="#0078d4")
        self.connect_btn.config(state=tk.DISABLED)
        target = self._do_connect_telnet if proto == "Telnet" else self._do_connect_ssh
        threading.Thread(target=target, daemon=True).start()

    def _do_connect_ssh(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(self.host_var.get().strip(), port=int(self.port_var.get()),
                                username=self.user_var.get().strip(), password=self.pass_var.get(),
                                timeout=10, look_for_keys=False, allow_agent=False)
            self.shell = self.client.invoke_shell(term="xterm-256color", width=COLS, height=ROWS)
            self.shell.settimeout(0.05)
            self.connected = True; self._stop_reader.clear()
            self.reader_thread = threading.Thread(target=self._reader_ssh, daemon=True)
            self.reader_thread.start()
            self.after(0, self._on_connected)
        except Exception as e:
            self.after(0, lambda: self._on_connect_fail(str(e)))

    def _do_connect_telnet(self):
        try:
            host = self.host_var.get().strip()
            port = int(self.port_var.get()) if self.port_var.get() else 23
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10); sock.connect((host, port)); sock.settimeout(0.05)
            self.tn = sock; self.connected = True; self._stop_reader.clear()
            self.reader_thread = threading.Thread(target=self._reader_telnet, daemon=True)
            self.reader_thread.start()
            self.after(0, self._on_connected)
        except Exception as e:
            self.after(0, lambda: self._on_connect_fail(str(e)))

    def _on_connected(self):
        self.connect_btn.config(state=tk.NORMAL, text="断开")
        self.status_var.set("● 已连接"); self.status_label.config(foreground="#1aaa55")
        self.text.focus_set()
        try: _save_terminal_settings({"host":self.host_var.get().strip(),"user":self.user_var.get().strip(),"password":self.pass_var.get(),"port":int(self.port_var.get())})
        except: pass

    def _on_connect_fail(self, err):
        self.connect_btn.config(state=tk.NORMAL)
        self.status_var.set("● 未连接"); self.status_label.config(foreground="#888888")

    def disconnect(self):
        self._stop_reader.set()
        # 等待 reader 线程退出
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1)
        for obj in (self.shell, self.client, self.tn):
            try:
                if obj: obj.close()
            except: pass
        self.shell = self.client = self.tn = None
        self.connected = False
        self.connect_btn.config(text="连接")
        self.status_var.set("● 未连接"); self.status_label.config(foreground="#888888")

    def _reader_ssh(self):
        while not self._stop_reader.is_set() and self.shell:
            try:
                if self.shell.recv_ready():
                    data = self.shell.recv(8192)
                    if data: self._inbuf.put(data)
                    else: break
                else: time.sleep(0.02)
            except: break
        try:
            if self.winfo_exists():
                self.after(0, lambda: setattr(self, 'connected', False) or self.status_label.config(foreground="#888888") or self.status_var.set("● 未连接") or self.connect_btn.config(text="连接"))
        except (tk.TclError, RuntimeError):
            self.connected = False
        except (tk.TclError, RuntimeError):
            self.connected = False

    def _reader_telnet(self):
        while not self._stop_reader.is_set() and self.tn:
            try:
                data = self.tn.recv(8192)
                if data: self._inbuf.put(data)
                else: break
            except socket.timeout: time.sleep(0.02)
            except: break
        try:
            if self.winfo_exists():
                self.after(0, lambda: setattr(self, 'connected', False) or self.status_label.config(foreground="#888888") or self.status_var.set("● 未连接") or self.connect_btn.config(text="连接"))
        except (tk.TclError, RuntimeError):
            self.connected = False

    def _schedule_refresh(self):
        try:
            if self.winfo_exists():
                self.after(REFRESH_INTERVAL, self._refresh)
        except (tk.TclError, RuntimeError):
            pass

    def _refresh(self):
        if not self.winfo_exists():
            return
        try:
            chunks = []
            for _ in range(200):
                try: data = self._inbuf.get_nowait()
                except queue.Empty: break
                chunks.append(data)
            if chunks:
                raw = b"".join(chunks)
                text_before = self._get_screen_text()
                self.stream.feed(raw.decode("utf-8", errors="replace"))
                text_after = self._get_screen_text()
                if text_after != text_before:
                    self._update_display(text_before, text_after)
        finally:
            self._schedule_refresh()

    def _get_screen_text(self):
        """从 pyte 屏幕提取当前内容为字符串"""
        lines = []
        for y in range(self.screen.lines):
            row = self.screen.buffer[y]
            line = "".join(row[x].data or " " for x in range(self.screen.columns))
            lines.append(line.rstrip())
        return "\n".join(lines)

    def _update_display(self, old_text, new_text):
        """智能更新显示：保留历史，只更新屏幕区"""
        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")

        # 找出旧屏幕里哪些行"滚出去"了（不再出现在新屏幕里）
        # 简单策略：如果新屏幕跟旧屏幕的后 N 行相同，则前面的行是滚出的
        scrolled_out = []
        if old_lines != new_lines:
            # 找最长的公共后缀
            common_suffix = 0
            for i in range(1, min(len(old_lines), len(new_lines)) + 1):
                if old_lines[-i] == new_lines[-i]:
                    common_suffix = i
                else:
                    break
            # 旧屏幕里不在公共后缀中的行 = 滚出去的
            if common_suffix < len(old_lines):
                scrolled_out = old_lines[:len(old_lines) - common_suffix]
                # 只保留非空行
                scrolled_out = [l for l in scrolled_out if l.strip()]

        yv = self.text.yview()
        at_bottom = yv[1] >= 0.9

        # 追加滚出的行到历史区（屏幕区上方）
        if scrolled_out:
            # 在屏幕区标记之前插入
            insert_pos = self.text.index("screen_start")
            for line in scrolled_out:
                self.text.insert(insert_pos, line + "\n")

        # 删除屏幕区并重画
        self.text.delete("screen_start", tk.END)
        # 去掉尾部空行
        display_lines = new_lines
        while display_lines and not display_lines[-1].strip():
            display_lines = display_lines[:-1]
        self.text.insert(tk.END, "\n".join(display_lines))

        # 限制总行数
        total = int(self.text.index("end-1c").split(".")[0])
        if total > 20000:
            excess = total - 20000
            self.text.delete("1.0", f"{excess}.0")

        # 光标和滚动
        self.text.mark_set(tk.INSERT, tk.END)
        if at_bottom:
            self.text.see(tk.END)


    def clear(self):
        if self.connected:
            self._send("clear\n")
        else:
            if self.screen: self.screen.reset()
            self.text.delete("1.0", tk.END)
            self.text.mark_set("screen_start", "1.0")

    def auto_connect(self, host, user, password, port=22):
        self.host_var.set(host); self.user_var.set(user); self.pass_var.set(password); self.port_var.set(port)
        if not self.connected: self.connect()

    def connect_to(self, host, user, password, port=22):
        if self.connected:
            if self.host_var.get().strip()==host and str(self.port_var.get())==str(port): return
            self.disconnect(); time.sleep(0.3)
        self.host_var.set(host); self.user_var.set(user); self.pass_var.set(password); self.port_var.set(port)
        self.connect()

    def wait_connected(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.connected: return True
            time.sleep(0.1)
        return self.connected

    def send_command(self, cmd):
        if not self.connected: return False
        self._send(cmd + "\n"); return True


class SshTerminalContainer(ttk.Frame):
    def __init__(self, parent, default_host="", default_user="admin",
                 default_pass="pica8", default_port=22):
        super().__init__(parent)
        self.default_host, self.default_user = default_host, default_user
        self.default_pass, self.default_port = default_pass, default_port
        self._counter = 0
        tb = ttk.Frame(self); tb.pack(side="top", fill="x", padx=2, pady=(2,0))
        ttk.Button(tb, text="+ 新建终端", width=12, command=self.new_terminal).pack(side="left", padx=2)
        ttk.Button(tb, text="× 关闭当前", width=12, command=self.close_current).pack(side="left", padx=2)
        ttk.Button(tb, text="重命名", width=8, command=self._rename_current).pack(side="left", padx=2)
        self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True)
        self.new_terminal()

    def new_terminal(self, host=None, user=None, password=None, port=None, auto_connect=False, title=None):
        self._counter += 1
        term = SshTerminal(self.nb,
            default_host=host or self.default_host, default_user=user or self.default_user,
            default_pass=password or self.default_pass, default_port=port or self.default_port)
        self.nb.add(term, text=f"  {title or f'终端 {self._counter}'}  ")
        self.nb.select(term)
        if auto_connect and host:
            term.auto_connect(host, user or self.default_user, password or self.default_pass, port or self.default_port)
        return term

    def close_current(self):
        if self.nb.index("end") <= 1: return
        cur = self.nb.select()
        if not cur: return
        w = self.nb.nametowidget(cur)
        if isinstance(w, SshTerminal) and w.connected: w.disconnect()
        self.nb.forget(cur)

    def _rename_current(self):
        cur = self.nb.select()
        if not cur: return
        from tkinter import simpledialog
        old = self.nb.tab(cur, "text").strip()
        new = simpledialog.askstring("重命名", "新名称:", initialvalue=old, parent=self)
        if new: self.nb.tab(cur, text=f"  {new.strip()}  ")

    def get_active_terminal(self):
        cur = self.nb.select()
        return self.nb.nametowidget(cur) if cur else None

    def get_or_create_terminal_for(self, host, user, password, port=22, title=None):
        for tid in self.nb.tabs():
            t = self.nb.nametowidget(tid)
            if isinstance(t, SshTerminal) and t.connected and t.host_var.get().strip()==host and str(t.port_var.get())==str(port):
                self.nb.select(tid); return t
        return self.new_terminal(host=host, user=user, password=password, port=port, auto_connect=True, title=title)

    def disconnect_all(self):
        for tid in self.nb.tabs():
            t = self.nb.nametowidget(tid)
            if isinstance(t, SshTerminal) and t.connected:
                try: t.disconnect()
                except: pass

    @property
    def connected(self):
        for tid in self.nb.tabs():
            t = self.nb.nametowidget(tid)
            if isinstance(t, SshTerminal) and t.connected: return True
        return False
