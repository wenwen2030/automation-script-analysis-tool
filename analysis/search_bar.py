"""搜索框组件：嵌入到 Text 控件上方，支持 Ctrl+F 触发、高亮匹配、上下跳转"""

import tkinter as tk
import tkinter.ttk as ttk


class SearchBar(ttk.Frame):
    """可嵌入的搜索条，绑定到一个 tk.Text 控件"""

    def __init__(self, parent, text_widget):
        super().__init__(parent)
        self.text_widget = text_widget
        self._matches = []
        self._current_idx = -1

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._on_search())

        ttk.Label(self, text="搜索:").pack(side="left", padx=(4, 2))
        self.entry = ttk.Entry(self, textvariable=self.search_var, width=30)
        self.entry.pack(side="left", padx=2)
        self.entry.bind("<Return>", lambda e: self.next_match())
        self.entry.bind("<Shift-Return>", lambda e: self.prev_match())

        ttk.Button(self, text="↑", width=3, command=self.prev_match).pack(side="left", padx=1)
        ttk.Button(self, text="↓", width=3, command=self.next_match).pack(side="left", padx=1)

        self.count_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.count_var, foreground="#888888").pack(side="left", padx=6)

        ttk.Button(self, text="×", width=3, command=self.hide).pack(side="right", padx=2)

        # 配置高亮 tag
        self.text_widget.tag_configure("search_hl", background="#5a4e00", foreground="#ffffff")
        self.text_widget.tag_configure("search_current", background="#0078d4", foreground="#ffffff")

    def show(self):
        self.grid(row=0, column=0, columnspan=2, sticky="ew")
        # 延迟聚焦确保控件已可见
        self.after(50, lambda: (self.entry.focus_set(), self.entry.select_range(0, tk.END)))

    def hide(self):
        self._clear_highlights()
        self.grid_remove()

    def toggle(self):
        if self.winfo_ismapped():
            self.hide()
        else:
            self.show()

    def _on_search(self):
        self._clear_highlights()
        query = self.search_var.get()
        if not query:
            self.count_var.set("")
            return

        self._matches = []
        start = "1.0"
        while True:
            pos = self.text_widget.search(query, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self.text_widget.tag_add("search_hl", pos, end)
            self._matches.append(pos)
            start = end

        if self._matches:
            self._current_idx = 0
            self._highlight_current()
            self.count_var.set(f"1/{len(self._matches)}")
        else:
            self._current_idx = -1
            self.count_var.set("无匹配")

    def next_match(self):
        if not self._matches:
            return
        self._current_idx = (self._current_idx + 1) % len(self._matches)
        self._highlight_current()

    def prev_match(self):
        if not self._matches:
            return
        self._current_idx = (self._current_idx - 1) % len(self._matches)
        self._highlight_current()

    def _highlight_current(self):
        self.text_widget.tag_remove("search_current", "1.0", tk.END)
        if 0 <= self._current_idx < len(self._matches):
            pos = self._matches[self._current_idx]
            end = f"{pos}+{len(self.search_var.get())}c"
            self.text_widget.tag_add("search_current", pos, end)
            self.text_widget.see(pos)
            self.count_var.set(f"{self._current_idx + 1}/{len(self._matches)}")

    def _clear_highlights(self):
        self.text_widget.tag_remove("search_hl", "1.0", tk.END)
        self.text_widget.tag_remove("search_current", "1.0", tk.END)
        self._matches = []
        self._current_idx = -1
