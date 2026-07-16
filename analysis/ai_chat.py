"""AI 分析对话标签页 — 接入 DeepSeek API 分析脚本日志"""

import threading
import tkinter as tk
import tkinter.ttk as ttk

from .. import theme

# DeepSeek 系统提示词
SYSTEM_PROMPT = """\
你是一位PicOS交换机自动化测试脚本日志分析专家。用户会提供测试脚本的运行日志，请你分析失败原因。

分析规则：
1. 先定位失败点（Fail/errExe/errScriptAborted/errDeviceDied）
2. 看 Expected 和 Got 的差异
3. 结合上下文判断是：功能bug / 脚本问题 / 环境问题 / 平台不支持 / 随机性问题

输出格式：
- **现象**：简述失败的具体表现
- **问题分类**：功能bug / 脚本问题 / 环境问题 / 平台不支持 / 其他
- **详细原因**：用简洁中文描述根因,同时需要有证据辅证,有发包的地方我希望你能给出这个包详细是如何组的
- **建议**：如何处理（重跑/修脚本/报bug/查环境）

注意：
- 如果日志显示 pass，直接说"脚本通过，无需分析"
- 如果是 errScriptAborted 看超时命令是什么
- 如果是 pica8CheckText Failed 看期望文本和实际输出的差异
- 回答用中文，简洁直接
"""


class AiChatTab(ttk.Frame):
    """AI 对话标签页，嵌入到分析窗口的 Notebook 中"""

    def __init__(self, parent, get_log_fn=None, get_script_name_fn=None):
        """
        Args:
            parent: Notebook 父容器
            get_log_fn: 回调函数，返回当前日志文本
            get_script_name_fn: 回调函数，返回当前脚本名
        """
        super().__init__(parent, padding=8)
        self.get_log_fn = get_log_fn
        self.get_script_name_fn = get_script_name_fn
        self.messages = []  # 对话历史
        self._streaming = False
        self._client = None
        self._build_ui()

    def _build_ui(self):
        pal = theme.palette()

        # 顶部工具栏
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))

        ttk.Label(toolbar, text="模型:").pack(side="left")
        self.model_var = tk.StringVar(value="deepseek-chat")
        model_combo = ttk.Combobox(
            toolbar, textvariable=self.model_var, width=20,
            values=["deepseek-chat", "deepseek-reasoner"],
            state="readonly"
        )
        model_combo.pack(side="left", padx=(4, 12))

        self.auto_log_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="自动附带日志",
                        variable=self.auto_log_var).pack(side="left")

        ttk.Button(toolbar, text="清空对话", width=10,
                   command=self._clear_chat).pack(side="right")

        # 对话显示区
        chat_frame = ttk.Frame(self)
        chat_frame.pack(fill="both", expand=True)

        self.chat_text = tk.Text(
            chat_frame, wrap=tk.WORD,
            bg=pal["bg"], fg=pal["fg"],
            font=("Consolas", 10), state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
            insertbackground=pal["fg"],
        )
        chat_sb = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL,
                                command=self.chat_text.yview)
        self.chat_text.config(yscrollcommand=chat_sb.set)
        self.chat_text.pack(side="left", fill="both", expand=True)
        chat_sb.pack(side="left", fill="y")

        # 对话文本样式
        self.chat_text.tag_configure("user_label",
                                     foreground="#569cd6", font=("Consolas", 10, "bold"))
        self.chat_text.tag_configure("ai_label",
                                     foreground="#4ec9b0", font=("Consolas", 10, "bold"))
        self.chat_text.tag_configure("user_msg", foreground="#d4d4d4")
        self.chat_text.tag_configure("ai_msg", foreground="#d4d4d4")
        self.chat_text.tag_configure("system_msg",
                                     foreground="#888888", font=("Consolas", 9, "italic"))
        self.chat_text.tag_configure("error_msg", foreground="#f44747")

        # 底部输入区
        input_frame = ttk.Frame(self)
        input_frame.pack(fill="x", pady=(6, 0))

        self.input_text = tk.Text(
            input_frame, height=3, wrap=tk.WORD,
            bg=pal["bg"], fg=pal["fg"],
            font=("Consolas", 10),
            insertbackground=pal["fg"],
            borderwidth=1, relief="solid", highlightthickness=0,
        )
        self.input_text.pack(side="left", fill="both", expand=True)

        btn_col = ttk.Frame(input_frame)
        btn_col.pack(side="right", padx=(6, 0))
        self.send_btn = ttk.Button(btn_col, text="发送", width=8,
                                   command=self._on_send)
        self.send_btn.pack(pady=2)
        ttk.Button(btn_col, text="分析日志", width=8,
                   command=self._quick_analyze).pack(pady=2)

        # Enter 发送，Shift+Enter 换行
        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", lambda e: None)  # 允许换行

    def _on_enter(self, event):
        """Enter 键发送消息"""
        if not event.state & 0x1:  # 没有按 Shift
            self._on_send()
            return "break"

    def _on_send(self):
        """发送用户输入的消息"""
        text = self.input_text.get("1.0", tk.END).strip()
        if not text or self._streaming:
            return
        self.input_text.delete("1.0", tk.END)

        # 首次对话且勾选了自动附带日志，自动注入日志上下文
        if self.auto_log_var.get() and not self.messages and self.get_log_fn:
            log_content = self.get_log_fn()
            if log_content:
                script_name = self.get_script_name_fn() if self.get_script_name_fn else "unknown"
                # 截取日志（最多取最后 8000 行，DeepSeek支持64K上下文）
                lines = log_content.splitlines()
                if len(lines) > 8000:
                    log_content = "\n".join(lines[-8000:])
                    log_content = f"[注: 日志过长，仅附带最后 8000 行]\n{log_content}"
                context_msg = f"以下是脚本 {script_name} 的运行日志:\n```\n{log_content}\n```\n\n{text}"
                text = context_msg

        self._append_chat("user", text)
        self.messages.append({"role": "user", "content": text})
        self._stream_response()

    def _quick_analyze(self):
        """一键分析当前日志"""
        if self._streaming:
            return
        if not self.get_log_fn:
            self._append_system("没有可用的日志内容")
            return
        log_content = self.get_log_fn()
        if not log_content:
            self._append_system("日志为空，无法分析")
            return

        script_name = self.get_script_name_fn() if self.get_script_name_fn else "unknown"
        lines = log_content.splitlines()
        if len(lines) > 8000:
            log_content = "\n".join(lines[-8000:])
            log_content = f"[注: 日志过长，仅附带最后 8000 行]\n{log_content}"

        prompt = f"请分析以下脚本 {script_name} 的运行日志，找出失败原因:\n```\n{log_content}\n```"

        self.input_text.delete("1.0", tk.END)
        # 显示简短用户消息
        self._append_chat("user", f"[一键分析] 分析脚本 {script_name} 的日志")
        self.messages.append({"role": "user", "content": prompt})
        self._stream_response()

    def _stream_response(self):
        """后台线程调用 DeepSeek API 并流式输出"""
        self._streaming = True
        self.send_btn.config(state=tk.DISABLED)
        self._append_chat_label("ai")
        threading.Thread(target=self._call_api, daemon=True).start()

    def _call_api(self):
        """实际调用 DeepSeek API"""
        try:
            client = self._get_client()

            # 构建增强的system prompt: 基础规则 + 知识库 + 经验
            enhanced_prompt = self._build_enhanced_prompt()
            messages = [{"role": "system", "content": enhanced_prompt}] + self.messages

            response = client.chat.completions.create(
                model=self.model_var.get(),
                messages=messages,
                stream=True,
                max_tokens=4096,
            )

            full_response = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    self.after(0, lambda t=token: self._append_stream_token(t))

            self.messages.append({"role": "assistant", "content": full_response})
            self.after(0, self._finish_stream)

        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._on_api_error(err))

    def _get_client(self):
        """获取或创建 OpenAI 客户端"""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise RuntimeError(
                    "未安装 openai 库，请执行: pip install openai")

            from ..config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
            if not DEEPSEEK_API_KEY:
                raise RuntimeError(
                    "未配置 DeepSeek API Key，请在 config.py 中设置 DEEPSEEK_API_KEY")

            self._client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
            )
        return self._client

    def _append_chat(self, role, text):
        """追加一条完整的聊天消息"""
        self.chat_text.config(state=tk.NORMAL)
        if role == "user":
            self.chat_text.insert(tk.END, "\n你: ", "user_label")
            # 用户消息如果很长（含日志），只显示前 200 字符
            display = text if len(text) <= 200 else text[:200] + "..."
            self.chat_text.insert(tk.END, display + "\n", "user_msg")
        else:
            self.chat_text.insert(tk.END, "\nAI: ", "ai_label")
            self.chat_text.insert(tk.END, text + "\n", "ai_msg")
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def _append_chat_label(self, role):
        """只追加角色标签，后续流式追加内容"""
        self.chat_text.config(state=tk.NORMAL)
        label = "\nAI: " if role == "ai" else "\n你: "
        tag = "ai_label" if role == "ai" else "user_label"
        self.chat_text.insert(tk.END, label, tag)
        self.chat_text.config(state=tk.DISABLED)

    def _append_stream_token(self, token):
        """流式追加一个 token"""
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.insert(tk.END, token, "ai_msg")
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def _finish_stream(self):
        """流式完成"""
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.insert(tk.END, "\n")
        self.chat_text.config(state=tk.DISABLED)
        self._streaming = False
        self.send_btn.config(state=tk.NORMAL)

    def _on_api_error(self, err):
        """API 调用出错"""
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.insert(tk.END, f"\n[错误] {err}\n", "error_msg")
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)
        self._streaming = False
        self.send_btn.config(state=tk.NORMAL)

    def _append_system(self, text):
        """追加系统提示"""
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.insert(tk.END, f"\n[系统] {text}\n", "system_msg")
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def _clear_chat(self):
        """清空对话历史"""
        self.messages.clear()
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        self.chat_text.config(state=tk.DISABLED)
        self._client = None  # 重置客户端，允许切换配置

    def _build_enhanced_prompt(self):
        """构建增强的system prompt: 基础规则 + 知识库匹配 + 分析经验"""
        parts = [SYSTEM_PROMPT]

        # 1. 注入知识库匹配结果(如果有日志)
        kb_context = self._get_kb_context()
        if kb_context:
            parts.append(kb_context)

        # 2. 注入分析经验指南
        exp_context = self._get_experience_context()
        if exp_context:
            parts.append(exp_context)

        # 3. 注入脚本源码摘要(如果能找到)
        source_context = self._get_source_context()
        if source_context:
            parts.append(source_context)

        return "\n\n".join(parts)

    def _get_kb_context(self):
        """从知识库中匹配已知问题,作为参考注入"""
        try:
            log_content = self.get_log_fn() if self.get_log_fn else ""
            if not log_content:
                return ""
            script_name = self.get_script_name_fn() if self.get_script_name_fn else ""

            from ..knowledge import match_knowledge
            matches = match_knowledge(log_content, script_name=script_name)

            if not matches:
                return ""

            # 只取top 5条,避免token过多
            top_matches = matches[:5]
            lines = ["## 知识库参考(历史上类似问题的已知根因)："]
            for i, m in enumerate(top_matches, 1):
                lines.append(f"{i}. [{m.category}] {m.cause}")
                if m.solution:
                    lines.append(f"   解决: {m.solution}")
                if m.script_name:
                    lines.append(f"   来源脚本: {m.script_name}")
            lines.append("")
            lines.append("请参考以上已知问题判断当前日志是否属于同类问题,但不要生搬硬套,要根据实际日志内容分析。")
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_experience_context(self):
        """读取分析经验指南"""
        try:
            import os
            # 查找经验文件
            possible_paths = [
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), ".kiro", "steering", "script-analysis.md"),
                os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), "script-analysis.md"),
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    # 截取关键部分(不超过2000字符)
                    if len(content) > 2000:
                        content = content[:2000] + "\n...(截断)"
                    return f"## 分析经验指南：\n{content}"
            return ""
        except Exception:
            return ""

    def _get_source_context(self):
        """尝试获取脚本源码摘要"""
        try:
            script_name = self.get_script_name_fn() if self.get_script_name_fn else ""
            if not script_name:
                return ""

            from .source_viewer import find_script_file
            script_path = find_script_file(script_name)
            if not script_path:
                return ""

            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()

            # 只取前100行(函数定义和描述部分)
            lines = source.splitlines()[:100]
            snippet = "\n".join(lines)
            if len(snippet) > 3000:
                snippet = snippet[:3000] + "\n...(截断)"

            return f"## 脚本源码(前100行,帮助理解测试目的)：\n```\n{snippet}\n```"
        except Exception:
            return ""
