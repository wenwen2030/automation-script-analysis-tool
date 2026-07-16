"""知识库匹配逻辑：正则匹配 + 加权排序"""

import re
from .storage import load_kb, batch_increment_hits
from .models import KBEntry


def match_knowledge(text, script_name="", step_info=""):
    """匹配日志文本，返回命中的条目列表（按加权分数降序）

    Args:
        text: 日志全文
        script_name: 当前脚本名（用于加权匹配）
        step_info: 当前Step信息（用于加权匹配）
    """
    entries = load_kb()
    matched = []
    for entry in entries:
        try:
            if re.search(entry.pattern, text, re.IGNORECASE):
                matched.append(entry)
        except re.error:
            # 正则无效，尝试纯文本匹配
            if entry.pattern.lower() in text.lower():
                matched.append(entry)

    # P2: 加权排序
    def _score(entry):
        score = entry.hit_count * 0.3
        # 脚本名匹配加权
        if script_name and entry.script_name:
            if script_name.lower() == entry.script_name.lower():
                score += 40
            elif _script_base(script_name) == _script_base(entry.script_name):
                # 同系列脚本（如 RateLimit_01_01 和 RateLimit_01_02）
                score += 20
        # Step匹配加权
        if step_info and entry.step_info:
            if step_info.lower() in entry.step_info.lower() or entry.step_info.lower() in step_info.lower():
                score += 30
        return score

    matched.sort(key=_score, reverse=True)

    # P0: 批量增加命中计数，一次性保存
    if matched:
        batch_increment_hits(matched)

    return matched


def _script_base(name):
    """提取脚本名的基础部分（去掉末尾数字编号）
    例: RateLimit_01_02 → RateLimit_01, SnmpWalk_02_05 → SnmpWalk_02
    """
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return name
