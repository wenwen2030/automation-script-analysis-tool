"""知识库存储：支持多后端（199服务器 / 飞书多维表格 / 本地）"""

import json
import os
import sys
from .models import KBEntry
from ..config import (
    KB_STORAGE_BACKEND as STORAGE_BACKEND,
    KB_REMOTE_HOST as REMOTE_KB_HOST,
    KB_REMOTE_USER as REMOTE_KB_USER,
    KB_REMOTE_PASS as REMOTE_KB_PASS,
    KB_REMOTE_DIR as REMOTE_KB_DIR,
    FEISHU_APP_ID, FEISHU_APP_SECRET,
    FEISHU_BITABLE_TOKEN, FEISHU_TABLE_ID,
)

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
    """加载知识库：根据后端配置选择数据源"""
    if STORAGE_BACKEND == "feishu":
        remote = _feishu_read()
        if remote is not None:
            _save_local(remote)
            return remote
        return _load_local()
    elif STORAGE_BACKEND == "ssh":
        remote = _read_remote()
        local = _load_local()
        if remote is not None:
            merged = _merge(local, remote)
            _save_local(merged)
            return merged
        return local
    else:
        return _load_local()


def save_kb(entries):
    """保存：根据后端配置选择存储方式"""
    if STORAGE_BACKEND == "feishu":
        _save_local(entries)
        _feishu_write(entries)
    elif STORAGE_BACKEND == "ssh":
        remote = _read_remote()
        if remote is not None:
            entries = _merge(entries, remote)
        _save_local(entries)
        _write_remote(entries)
    else:
        _save_local(entries)


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
    """增加命中计数（单条，保留兼容）"""
    batch_increment_hits([entry])


def batch_increment_hits(matched_entries):
    """批量增加命中计数 — 只更新本地缓存,不触发飞书全量写入"""
    entries = load_kb()
    matched_keys = {(e.pattern, e.cause) for e in matched_entries}
    changed = False
    for e in entries:
        if (e.pattern, e.cause) in matched_keys:
            e.hit_count += 1
            changed = True
    if changed:
        _save_local(entries)  # 只写本地,不触发飞书全量重写


# ======== 飞书多维表格后端 ========


def _feishu_get_tenant_token():
    """获取飞书 tenant_access_token(引用公共模块)"""
    from ..integrations.feishu_client import get_tenant_token
    return get_tenant_token()


def _feishu_request(method, path, body=None):
    """发送飞书 API 请求"""
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    token = _feishu_get_tenant_token()
    if not token:
        return None

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_BITABLE_TOKEN}/tables/{FEISHU_TABLE_ID}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError):
        return None


def _feishu_record_to_entry(record):
    """飞书记录转 KBEntry"""
    fields = record.get("fields", {})
    return KBEntry(
        pattern=_feishu_get_text(fields.get("匹配模式", "")),
        cause=_feishu_get_text(fields.get("失败原因", "")),
        solution=_feishu_get_text(fields.get("解决方法", "")),
        category=_feishu_get_text(fields.get("分类", "其他")),
        script_name=_feishu_get_text(fields.get("脚本名", "")),
        step_info=_feishu_get_text(fields.get("所属Step", "")),
        added_by=_feishu_get_text(fields.get("提交人", "")),
        added_at=str(fields.get("添加时间", "")),
        hit_count=int(fields.get("命中次数", 0) or 0),
    )


def _feishu_get_text(val):
    """从飞书字段值提取纯文本（处理富文本格式）"""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        # 富文本格式: [{"text": "xxx"}]
        return "".join(item.get("text", "") for item in val if isinstance(item, dict))
    return str(val) if val else ""


def _feishu_entry_to_fields(entry):
    """KBEntry 转飞书字段"""
    return {
        "匹配模式": entry.pattern,
        "失败原因": entry.cause,
        "解决方法": entry.solution,
        "分类": entry.category,
        "脚本名": entry.script_name,
        "所属Step": entry.step_info,
        "提交人": entry.added_by,
        "添加时间": entry.added_at,
        "命中次数": entry.hit_count,
    }


def _feishu_read():
    """从飞书多维表格读取所有知识库条目"""
    if not FEISHU_APP_ID or not FEISHU_BITABLE_TOKEN:
        return None

    entries = []
    page_token = ""
    while True:
        path = f"/records?page_size=500"
        if page_token:
            path += f"&page_token={page_token}"
        result = _feishu_request("GET", path)
        if not result or result.get("code") != 0:
            return None if not entries else entries
        data = result.get("data", {})
        items = data.get("items", [])
        for item in items:
            entry = _feishu_record_to_entry(item)
            # 把 record_id 存起来用于后续更新
            entry._record_id = item.get("record_id", "")
            entries.append(entry)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")

    return entries


def _feishu_write(entries):
    """全量写入飞书多维表格（清空后重写）"""
    if not FEISHU_APP_ID or not FEISHU_BITABLE_TOKEN:
        return

    # 先删除所有现有记录
    existing = _feishu_read()
    if existing:
        record_ids = [getattr(e, "_record_id", "") for e in existing if getattr(e, "_record_id", "")]
        # 批量删除(每次最多500条)
        for i in range(0, len(record_ids), 500):
            batch = record_ids[i:i+500]
            _feishu_request("POST", "/records/batch_delete", {"records": batch})

    # 批量新增(每次最多500条)
    for i in range(0, len(entries), 500):
        batch = entries[i:i+500]
        records = [{"fields": _feishu_entry_to_fields(e)} for e in batch]
        _feishu_request("POST", "/records/batch_create", {"records": records})


def _feishu_add_entry(entry):
    """飞书添加单条记录"""
    if not FEISHU_APP_ID or not FEISHU_BITABLE_TOKEN:
        return
    body = {"fields": _feishu_entry_to_fields(entry)}
    _feishu_request("POST", "/records", body)
