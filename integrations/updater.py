"""版本更新检测 — 通过 GitHub Releases API 检查新版本"""

import json
import threading
import webbrowser
from urllib.request import urlopen, Request
from urllib.error import URLError

from ..config import APP_VERSION, GITHUB_REPO


def _parse_version(v):
    """将版本字符串解析为可比较的元组,支持 'v1.2.3' 或 '1.2.3'"""
    v = v.lstrip("vV")
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _check_update_sync():
    """同步检查更新,返回 (new_version, release_notes, download_url) 或 None"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MonitorTool-UpdateChecker",
    })

    try:
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError):
        return None

    tag = data.get("tag_name", "")
    if not tag:
        return None

    remote_ver = _parse_version(tag)
    local_ver = _parse_version(APP_VERSION)

    if remote_ver <= local_ver:
        return None

    # 获取下载链接(优先 .exe asset,其次 release 页面)
    download_url = data.get("html_url", "")
    assets = data.get("assets", [])
    for asset in assets:
        name = asset.get("name", "").lower()
        if name.endswith(".exe"):
            download_url = asset.get("browser_download_url", download_url)
            break

    release_notes = data.get("body", "") or ""
    return tag, release_notes, download_url


def check_update(parent_window=None):
    """后台线程检查更新,有新版时弹窗提示

    Args:
        parent_window: Tk root 窗口,用于弹窗定位。如果为 None 则静默。
    """
    def _worker():
        result = _check_update_sync()
        if result and parent_window:
            tag, notes, url = result
            parent_window.after(0, lambda: _show_update_dialog(parent_window, tag, notes, url))

    threading.Thread(target=_worker, daemon=True).start()


def _show_update_dialog(parent, version, notes, download_url):
    """弹出更新提示对话框"""
    import tkinter as tk
    import tkinter.ttk as ttk

    dialog = tk.Toplevel(parent)
    dialog.title("发现新版本")
    dialog.geometry("500x380")
    dialog.resizable(True, True)
    dialog.transient(parent)
    dialog.grab_set()

    # 居中显示
    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 380) // 2
    dialog.geometry(f"+{x}+{y}")

    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)

    # 标题
    ttk.Label(frame, text=f"🎉 新版本可用: {version}",
              font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(frame, text=f"当前版本: v{APP_VERSION}",
              foreground="#888888").pack(anchor="w", pady=(2, 10))

    # 更新日志
    ttk.Label(frame, text="更新内容:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
    notes_text = tk.Text(
        frame, wrap=tk.WORD, height=12,
        font=("Consolas", 9),
        borderwidth=1, relief="solid", highlightthickness=0,
    )
    notes_text.pack(fill="both", expand=True, pady=(4, 10))
    notes_text.insert(tk.END, notes if notes else "(无更新说明)")
    notes_text.config(state=tk.DISABLED)

    # 按钮
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill="x")

    def _download():
        webbrowser.open(download_url)
        dialog.destroy()

    ttk.Button(btn_frame, text="立即下载", command=_download).pack(side="left")
    ttk.Button(btn_frame, text="稍后再说", command=dialog.destroy).pack(side="right")
