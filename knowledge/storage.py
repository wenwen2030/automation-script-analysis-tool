"""知识库存储：远程（199服务器）+ 本地缓存，带合并冲突保护"""

import json
import os
import sys
from .models import KBEntry

# 远程知识库服务器
REMOTE_KB_HOST = "10.28.164.199"
REMOTE_KB_USER = "admin"
REMOTE_KB_PASS = "pica8"
REMOTE_KB_DIR = "/home/pica8/Log/Ableson.Niu/knowledge_base"
REMOTE_KB_PATH = f"{REMOTE_KB_DIR}/knowledge_base.json"

_ssh_info = {"host": REMOTE_KB_HOST, "user": REMOTE_KB_USER, "password": REMOTE_KB_PASS}


def set_ssh_info(host=None, user=None, password=None):
    """覆盖默认连接信息（可选）"""
    if host:
        _ssh_info["host"] = host
    if user:
        _ssh_info["user"] = user
    if password:
        _ssh_info["password"] = password


def _local_kb_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "monitor_tool", "knowledge_base.json")


def _get_client():
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(_ssh_info["host"], username=_ssh_info["user"],
                       password=_ssh_info["password"], timeout=5,
                       look_for_keys=False, allow_agent=False)
        return client
    except Exception:
        return None


def _read_remote():
    client = _get_client()
    if not client:
        return None
    try:
        _, stdout, _ = client.exec_command(f"cat {REMOTE_KB_PATH} 2>/dev/null")
        data = stdout.read().decode("utf-8", errors="replace").strip()
        client.close()
        if data:
            raw = json.loads(data)
            if isinstance(raw, list):
                return [KBEntry.from_dict(d) for d in raw]
    except Exception:
        pass
    return None


def _write_remote(entries):
    client = _get_client()
    if not client:
        return False
    try:
        client.exec_command(f"mkdir -p {REMOTE_KB_DIR}")
        content = json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=2)
        sftp = client.open_sftp()
        try:
            with sftp.file(REMOTE_KB_PATH, "w") as f:
                f.write(content.encode("utf-8"))
        finally:
            sftp.close()
        client.close()
        return True
    except Exception:
        return False


def _load_local():
    path = _local_kb_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                return [KBEntry.from_dict(d) for d in raw]
        except Exception:
            pass
    return []


def _save_local(entries):
    path = _local_kb_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in entries], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _merge(local, remote):
    """合并本地和远程条目（按 pattern+cause 去重，保留 hit_count 较大的）"""
    seen = {}
    for e in remote:
        key = (e.pattern, e.cause)
        seen[key] = e
    for e in local:
        key = (e.pattern, e.cause)
        if key not in seen:
            seen[key] = e
        else:
            # 保留 hit_count 较大的
            if e.hit_count > seen[key].hit_count:
                seen[key].hit_count = e.hit_count
    return list(seen.values())


def load_kb():
    """加载知识库：优先远程，合并本地"""
    remote = _read_remote()
    local = _load_local()
    if remote is not None:
        merged = _merge(local, remote)
        _save_local(merged)
        return merged
    return local


def save_kb(entries):
    """保存：先写远程（带合并），再写本地"""
    # 读取远程最新版本
    remote = _read_remote()
    if remote is not None:
        entries = _merge(entries, remote)
    _save_local(entries)
    _write_remote(entries)


def add_entry(entry):
    """添加一条（KBEntry 对象）"""
    entries = load_kb()
    entries.insert(0, entry)
    save_kb(entries)
    return entries


def delete_entry(index):
    entries = load_kb()
    if 0 <= index < len(entries):
        entries.pop(index)
        save_kb(entries)
    return entries


def update_entry(index, entry):
    entries = load_kb()
    if 0 <= index < len(entries):
        entries[index] = entry
        save_kb(entries)
    return entries


def increment_hit(entry):
    """增加命中计数"""
    entries = load_kb()
    for e in entries:
        if e.pattern == entry.pattern and e.cause == entry.cause:
            e.hit_count += 1
            break
    save_kb(entries)
