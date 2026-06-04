"""知识库匹配逻辑：正则匹配 + 置信度排序"""

import re
from .storage import load_kb, increment_hit
from .models import KBEntry


def match_knowledge(text):
    """匹配日志文本，返回命中的条目列表（按 hit_count 降序）"""
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

    # 按命中次数降序（置信度高的排前面）
    matched.sort(key=lambda e: e.hit_count, reverse=True)

    # 增加命中计数
    for entry in matched:
        increment_hit(entry)

    return matched
