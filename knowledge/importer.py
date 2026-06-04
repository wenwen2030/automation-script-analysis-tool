"""知识库批量导入：支持 CSV 和 JSON 格式"""

import csv
import json
import os
from tkinter import filedialog, messagebox

from .models import KBEntry
from .storage import load_kb, save_kb


def import_from_file(parent_window=None):
    """弹出文件选择框，导入 CSV 或 JSON 到知识库

    CSV 格式要求列：pattern, cause, solution, category（后两列可选）
    JSON 格式：[{"pattern": ..., "cause": ..., ...}, ...]

    返回导入条数
    """
    path = filedialog.askopenfilename(
        parent=parent_window,
        title="导入知识库",
        filetypes=[
            ("CSV 文件", "*.csv"),
            ("JSON 文件", "*.json"),
            ("所有文件", "*.*"),
        ],
    )
    if not path:
        return 0

    ext = os.path.splitext(path)[1].lower()
    new_entries = []

    try:
        if ext == ".csv":
            new_entries = _parse_csv(path)
        elif ext == ".json":
            new_entries = _parse_json(path)
        else:
            messagebox.showerror("格式错误", "仅支持 .csv 和 .json 文件", parent=parent_window)
            return 0
    except Exception as e:
        messagebox.showerror("导入失败", f"解析文件出错: {e}", parent=parent_window)
        return 0

    if not new_entries:
        messagebox.showinfo("导入结果", "文件中没有有效条目", parent=parent_window)
        return 0

    # 合并到现有知识库
    existing = load_kb()
    existing_keys = {(e.pattern, e.cause) for e in existing}
    added = 0
    for entry in new_entries:
        key = (entry.pattern, entry.cause)
        if key not in existing_keys:
            existing.insert(0, entry)
            existing_keys.add(key)
            added += 1

    if added > 0:
        save_kb(existing)

    messagebox.showinfo("导入完成",
                        f"共解析 {len(new_entries)} 条，新增 {added} 条（跳过 {len(new_entries)-added} 条重复）",
                        parent=parent_window)
    return added


def _parse_csv(path):
    entries = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pattern = row.get("pattern", "").strip()
            cause = row.get("cause", "").strip()
            if not pattern or not cause:
                continue
            entries.append(KBEntry(
                pattern=pattern,
                cause=cause,
                solution=row.get("solution", "").strip(),
                category=row.get("category", "其他").strip(),
            ))
    return entries


def _parse_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return [KBEntry.from_dict(d) for d in data if d.get("pattern") and d.get("cause")]
