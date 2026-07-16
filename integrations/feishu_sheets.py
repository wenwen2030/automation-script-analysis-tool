"""飞书电子表格操作 — 脚本PASS时自动填写H/I列"""

import json
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from .feishu_client import get_tenant_token, feishu_request

# 列映射
COL_TEST_ID = "A"
COL_CATEGORY = "H"      # 问题分类
COL_REASON = "I"        # 问题详细原因


def _extract_test_id(cell_value):
    """从单元格值提取TEST ID(处理链接格式)"""
    if cell_value is None:
        return ""
    if isinstance(cell_value, str):
        return cell_value.strip()
    if isinstance(cell_value, list):
        parts = []
        for item in cell_value:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return str(cell_value).strip()


def find_script_row(spreadsheet_token, sheet_id, script_name, log_fn=None):
    """在表格中查找脚本名对应的行号,返回行号(int)或None"""
    if log_fn is None:
        log_fn = lambda msg, tag="info": print(msg)

    token = get_tenant_token()
    if not token:
        log_fn("飞书token获取失败", "error")
        return None

    start_row = 16
    while start_row < 500:
        end_row = start_row + 99
        range_str = f"{sheet_id}!{COL_TEST_ID}{start_row}:{COL_TEST_ID}{end_row}"
        read_url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_str}"
        req = Request(read_url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            log_fn(f"读取表格失败: {e}", "error")
            return None

        values = data.get("data", {}).get("valueRange", {}).get("values", [])
        if not values:
            break

        for i, row in enumerate(values):
            cell = row[0] if row else None
            test_id = _extract_test_id(cell)
            if test_id and test_id.lower() == script_name.lower():
                return start_row + i

        if len(values) < 100:
            break
        start_row += 100

    return None


def fill_pass_result(spreadsheet_token, sheet_id, script_name, log_fn=None,
                     host="", user="", password="", monitor_dir=""):
    """脚本PASS时,在飞书表格中填写H/I列"""
    if log_fn is None:
        log_fn = lambda msg, tag="info": print(msg)

    if not spreadsheet_token or not sheet_id:
        return False

    token = get_tenant_token()
    if not token:
        log_fn("飞书token获取失败,跳过结果填写", "error")
        return False

    # 1. 查找脚本所在行
    row_num = find_script_row(spreadsheet_token, sheet_id, script_name, log_fn)
    if not row_num:
        log_fn(f"飞书表格中未找到 {script_name},跳过填写", "error")
        return False

    # 2. 写入H/I列
    range_hi = f"{sheet_id}!{COL_CATEGORY}{row_num}:{COL_REASON}{row_num}"
    write_url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values"
    write_body = json.dumps({
        "valueRange": {
            "range": range_hi,
            "values": [["其他问题", "重跑PASS"]]
        }
    }).encode()
    req = Request(write_url, data=write_body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }, method="PUT")
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") == 0:
            log_fn(f"✓ 飞书表格已更新: {script_name} (第{row_num}行) → 重跑PASS", "success")
            return True
        else:
            log_fn(f"飞书写入失败: {data.get('msg', '')}", "error")
            return False
    except (HTTPError, Exception) as e:
        log_fn(f"飞书写入异常: {e}", "error")
        return False


def fill_pass_async(spreadsheet_token, sheet_id, script_name, log_fn=None,
                    host="", user="", password="", monitor_dir=""):
    """异步填写(不阻塞主流程)"""
    threading.Thread(
        target=fill_pass_result,
        args=(spreadsheet_token, sheet_id, script_name, log_fn,
              host, user, password, monitor_dir),
        daemon=True
    ).start()
