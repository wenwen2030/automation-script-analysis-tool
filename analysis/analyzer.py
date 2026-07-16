"""核心分析逻辑：日志解析、模式匹配、结果提取

从 log_analyzer.py 迁移，增强了多 fail 点支持。
"""

import hashlib
import os
import re
import sys
import tempfile
import threading
import time
import paramiko


# SSH连接复用公共模块
from ..ssh_utils import get_ssh_client as _get_ssh_client, close_all_ssh


def _get_cache_dir():
    """日志本地缓存目录"""
    base = os.path.join(tempfile.gettempdir(), "monitor_tool_log_cache")
    os.makedirs(base, exist_ok=True)
    return base


def _cache_key(host, user, remote_path):
    h = hashlib.md5(f"{host}|{user}|{remote_path}".encode()).hexdigest()
    return os.path.join(_get_cache_dir(), h + ".log")


# 失败状态判定
RESULT_PATTERNS = {
    "pass": re.compile(r"script finished:\s*pass", re.I),
    "fail": re.compile(r"script finished:\s*fail", re.I),
    "errScriptAborted": re.compile(r"errScriptAborted"),
    "errScriptCrashed": re.compile(r"errScriptCrashed"),
    "errDeviceDied": re.compile(r"errDeviceDied"),
}

# 关键事件模式
FAIL_LINE_RE = re.compile(r"\bFail\b.*", re.I)
ERR_LINE_RE = re.compile(r"#Err\b.*")
ERREXE_RE = re.compile(r"errExe\s*\{(.+?)\}")
TIMEOUT_RE = re.compile(r"timeout\s+on:\s*ip:\s*(\S+).*?csl:\s*(\S+)", re.I)
EXPECTED_RE = re.compile(r"Expected[: ]+(.+?)(?:Got|got|$)", re.I)
GOT_RE = re.compile(r"\bGot[: ]+(.+)", re.I)
TITLE_RE = re.compile(r"sTitle.*?[\"\']([^\"\']+)[\"\']")
DESC_RE = re.compile(r"sDescription.*?[\"\']([^\"\']+)[\"\']")

# Step 描述匹配 — 从 pInfo "::Step X  描述" 输出中提取
# 日志里通常会出现: pInfo "::Step 2  Port1 send the packets..."
STEP_RE = re.compile(
    r'pInfo\s+["\']?:*Step\s*([\d.]+)\s*[:：\-]?\s*([^"\'\n]+)["\']?', re.I)
# 在日志输出里 Step 行通常是: "::Step 2  Port1 send the packets..."
STEP_LOG_RE = re.compile(r":*Step\s*([\d.]+)\s*[:：\-]?\s*(.+)", re.I)

# 组包指令（脚本里）
PKT_BUILD_RE = re.compile(
    r'wixBuildPacket_[^\n]*?'
    r'(?:port\s+"[^"]*"\s*\\?\s*)?'
    r'stream\s+"([^"]*)"\s*\\?\s*'
    r'(?:protocol\s+"([^"]*)"\s*\\?\s*)?'
    r'(?:ip\s+"([^"]*)")?',
    re.I | re.S)

# 常见模式 → 可能根因
PATTERN_HINTS = [
    (re.compile(r"pica8CheckText\s+Fail", re.I),
     "期望某文本未在设备输出中找到 → 检查相关命令实际输出，确认功能或时序"),
    (re.compile(r"pica8CheckNoText\s+Fail", re.I),
     "期望输出不包含某文本但实际出现 → 检查残留状态或非预期行为"),
    (re.compile(r"Fail.*userDefinedStat", re.I),
     "Ixia 测试仪收包数量不符合预期 → 检查转发路径/ECMP 哈希/硬件表项"),
    (re.compile(r"Ecmp hash Fail", re.I),
     "ECMP 负载均衡比例不符合预期 → 检查 hash 算法配置和硬件表项下发"),
    (re.compile(r"forward-host.*empty", re.I),
     "ARP 学习成功但硬件 forward-host 为空 → 硬件转发表同步延迟/失败"),
    (re.compile(r"sudo.*timeout|timeout.*sudo", re.I),
     "sudo 命令超时 → 可能需要密码确认或终端宽度不足导致命令截断"),
    (re.compile(r"eof\s+while\s+login", re.I),
     "登录时连接断开 → 串口被占用、SSH 数超限或设备刚重启"),
    (re.compile(r"breakout.*not.*found|不存在.*breakout", re.I),
     "breakout 提示未出现 → 交换机已重启过，breakout 已生效"),
]


def ssh_read_file(host, user, password, remote_path, use_cache=True, max_age=300):
    """通过 SSH/SFTP 读取远程文件全部内容

    use_cache: 是否使用本地缓存
    max_age: 缓存有效期（秒），默认 5 分钟
    """
    cache_path = _cache_key(host, user, remote_path)

    # 检查远程文件大小和修改时间，跟本地缓存比对
    client = _get_ssh_client(host, user, password)

    # 用 stat 拿远程文件大小和 mtime
    remote_size = None
    remote_mtime = None
    try:
        sftp = client.open_sftp()
        try:
            stat = sftp.stat(remote_path)
            remote_size = stat.st_size
            remote_mtime = stat.st_mtime
        finally:
            sftp.close()
    except Exception:
        pass

    # 检查本地缓存是否还有效
    if use_cache and os.path.isfile(cache_path) and remote_size is not None:
        try:
            local_size = os.path.getsize(cache_path)
            local_mtime = os.path.getmtime(cache_path)
            # 大小相同 + 缓存时间晚于远程 mtime → 直接用缓存
            if local_size == remote_size and (
                    remote_mtime is None or local_mtime >= remote_mtime):
                with open(cache_path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
        except Exception:
            pass

    # 重新下载（用 SFTP prefetch 加速）
    sftp = client.open_sftp()
    try:
        remote_file = sftp.open(remote_path, "rb")
        try:
            remote_file.prefetch()  # 启用 read-ahead，大文件下载快很多
            data = remote_file.read()
        finally:
            remote_file.close()
    finally:
        sftp.close()

    text = data.decode("utf-8", errors="replace")
    # 写入本地缓存
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    return text


def detect_result(text):
    for name, pat in RESULT_PATTERNS.items():
        if pat.search(text):
            return name
    return "unknown"


def extract_meta(text):
    title = TITLE_RE.search(text)
    desc = DESC_RE.search(text)
    return {
        "title": title.group(1).strip() if title else None,
        "description": desc.group(1).strip() if desc else None,
    }


def find_failure_lines(text, limit=50):
    """找出所有 Fail / #Err / errExe 关键行（含行号），最多 limit 条"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if FAIL_LINE_RE.search(line) or ERR_LINE_RE.search(line) or "errExe" in line:
            hits.append((i, line.rstrip()))
            if len(hits) >= limit:
                break
    return hits


def get_context(text, line_no, before=8, after=8):
    lines = text.splitlines()
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no - 1 + after + 1)
    return [(i + 1, lines[i]) for i in range(start, end)]


def extract_expected_got(snippet):
    expected = EXPECTED_RE.search(snippet)
    got = GOT_RE.search(snippet)
    return (
        expected.group(1).strip() if expected else None,
        got.group(1).strip() if got else None,
    )


def match_patterns(text):
    hints = []
    for pat, hint in PATTERN_HINTS:
        if pat.search(text):
            hints.append(hint)
    return hints


def find_step_before_line(text, fail_line_no):
    """在 fail 行之前找最近的 Step 描述"""
    lines = text.splitlines()
    for i in range(min(fail_line_no - 1, len(lines) - 1), -1, -1):
        m = STEP_LOG_RE.search(lines[i])
        if m:
            return {
                "step_no": m.group(1).strip(),
                "step_desc": m.group(2).strip(),
                "line_no": i + 1,
            }
    return None


def extract_fail_phenomenon(text, fail_line_no, lines_around=15):
    """提取 fail 处的现象描述（含 Expected/Got 完整日志）"""
    lines = text.splitlines()
    if fail_line_no - 1 >= len(lines):
        return ""
    # 取 fail 行本身 + 后续行直到遇到下一个 #Proc 或空行块
    detail_parts = []
    start = fail_line_no - 1
    end = min(start + lines_around, len(lines))
    for i in range(start, end):
        line = lines[i].rstrip()
        detail_parts.append(line)
        # 如果遇到分隔线后又遇到新的时间戳行，停止
        if i > start and line and line[0].isdigit() and ":" in line[:8] and "[line:" in line:
            # 这是下一条日志行了，不要它
            detail_parts.pop()
            break
    return "\n".join(detail_parts)


def find_local_script(script_name, search_dir=None):
    """在本地搜索脚本源码文件（使用索引加速）"""
    from .script_index import find_script
    return find_script(script_name)


def extract_packet_info_near_step(script_path, step_desc, step_no=""):
    """在源码中根据 step 描述定位附近的 wixBuildPacket_ 组包信息"""
    if not script_path or not os.path.isfile(script_path):
        return None
    try:
        with open(script_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    # 查找 step 在源码里的位置
    step_pattern = re.compile(
        rf'pInfo\s+["\']?:*Step\s*{re.escape(step_no)}\s*[:：\-]?\s*[^"\'\n]*["\']?'
        if step_no else rf'pInfo\s+["\']?:*Step[^\n]*{re.escape(step_desc[:20])}',
        re.I)
    m = step_pattern.search(content)
    if not m:
        return None

    # 在 step 之后 200 行内查找最近的 wixBuildPacket_
    start = m.end()
    snippet = content[start:start + 5000]
    pkt_match = PKT_BUILD_RE.search(snippet)
    if not pkt_match:
        # 也在 step 之前看一下
        before_snippet = content[max(0, m.start() - 5000):m.start()]
        pkt_match = PKT_BUILD_RE.search(before_snippet)
        if not pkt_match:
            return None

    return {
        "stream": pkt_match.group(1).strip() if pkt_match.group(1) else "",
        "protocol": pkt_match.group(2).strip() if pkt_match.group(2) else "",
        "ip": pkt_match.group(3).strip() if pkt_match.group(3) else "",
    }


def analyze(text, script_name=None, search_dir=None):
    """分析日志文本，返回结构化结果

    script_name: 用于定位本地脚本源码以提取组包信息
    search_dir: 脚本源码搜索目录（默认 Z:\\automation\\suite\\xorplus）
    """
    result = detect_result(text)
    meta = extract_meta(text)
    failures = find_failure_lines(text)

    # 为每个 fail 点生成上下文 + step + 现象 + 组包
    script_path = find_local_script(script_name) if script_name else None
    fail_contexts = []
    for line_no, _ in failures:
        ctx = get_context(text, line_no)
        snippet = "\n".join(l for _, l in ctx)
        exp, got = extract_expected_got(snippet)
        step = find_step_before_line(text, line_no)
        phenomenon = extract_fail_phenomenon(text, line_no)
        packet = None
        if step and script_path:
            packet = extract_packet_info_near_step(
                script_path, step["step_desc"], step["step_no"])
        fail_contexts.append({
            "line_no": line_no,
            "context": ctx,
            "expected": exp,
            "got": got,
            "step": step,
            "phenomenon": phenomenon,
            "packet": packet,
        })

    first_fail_ctx = fail_contexts[0]["context"] if fail_contexts else None
    expected = fail_contexts[0]["expected"] if fail_contexts else None
    got = fail_contexts[0]["got"] if fail_contexts else None

    timeouts = []
    for m in ERREXE_RE.finditer(text):
        body = m.group(1)
        tmatch = TIMEOUT_RE.search(body)
        if tmatch:
            timeouts.append({"ip": tmatch.group(1), "csl": tmatch.group(2), "raw": body})
        else:
            timeouts.append({"raw": body})

    hints = match_patterns(text)

    # 匹配用户自定义知识库
    from ..knowledge import match_knowledge
    kb_matches = match_knowledge(text, script_name=script_name or "")

    # 中文摘要
    parts = [f"测试结果: {result.upper()}"]
    if meta["title"]:
        parts.append(f"测试目标: {meta['title']}")
    if meta["description"]:
        parts.append(f"测试描述: {meta['description']}")
    if failures:
        parts.append(f"共发现 {len(failures)} 处失败/错误关键行，首条在第 {failures[0][0]} 行")
    if expected or got:
        if expected:
            parts.append(f"期望: {expected}")
        if got:
            parts.append(f"实际: {got}")
    if timeouts:
        parts.append(f"检测到 {len(timeouts)} 次命令超时（errExe）")
    if hints:
        parts.append("可能根因:\n  - " + "\n  - ".join(hints))
    if kb_matches:
        parts.append("已知问题（知识库匹配）:")
        for km in kb_matches:
            cause = km.cause if hasattr(km, "cause") else km.get("cause", "")
            solution = km.solution if hasattr(km, "solution") else km.get("solution", "")
            parts.append(f"  ★ {cause}")
            if solution:
                parts.append(f"    解决: {solution}")
    if result == "errScriptAborted":
        parts.append("脚本异常中止（命令超时） — 通常因交互式提示未处理或终端宽度不足")
    elif result == "errScriptCrashed":
        parts.append("脚本崩溃 — 通常因检查循环超时、变量错误或设备状态未就绪")
    elif result == "errDeviceDied":
        parts.append("设备连接丢失 — 设备重启、串口占用、SSH 数超限等")

    return {
        "result": result,
        "meta": meta,
        "failures": failures,
        "fail_contexts": fail_contexts,
        "first_fail_ctx": first_fail_ctx,
        "expected": expected,
        "got": got,
        "timeouts": timeouts,
        "hints": hints,
        "kb_matches": kb_matches,
        "summary": "\n".join(parts),
    }


def analyze_remote(host, user, password, log_file, script_name=None):
    """从远程主机下载日志并分析"""
    text = ssh_read_file(host, user, password, log_file)
    return analyze(text, script_name=script_name), text
