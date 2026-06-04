"""知识库数据模型"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# 分类定义
CATEGORIES = [
    "环境问题",
    "功能bug",
    "时序问题",
    "脚本问题",
    "配置问题",
    "硬件问题",
    "随机性问题",
    "其他",
]


@dataclass
class KBEntry:
    pattern: str              # 匹配模式（正则或关键词）
    cause: str                # 根因描述
    solution: str = ""        # 解决方法
    category: str = "其他"    # 分类
    script_name: str = ""     # 来源脚本名
    step_info: str = ""       # 来源 Step 信息
    added_by: str = ""        # 添加人
    added_at: str = ""        # 添加时间
    hit_count: int = 0        # 命中次数

    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        # 兼容旧格式（没有新字段的条目）
        return cls(
            pattern=d.get("pattern", ""),
            cause=d.get("cause", ""),
            solution=d.get("solution", ""),
            category=d.get("category", "其他"),
            script_name=d.get("script_name", ""),
            step_info=d.get("step_info", ""),
            added_by=d.get("added_by", ""),
            added_at=d.get("added_at", ""),
            hit_count=d.get("hit_count", 0),
        )
