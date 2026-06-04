"""知识库子包：团队共享的失败模式 → 根因映射"""

from .storage import load_kb, save_kb, add_entry, delete_entry, update_entry
from .matcher import match_knowledge
from .models import KBEntry, CATEGORIES
from .storage import set_ssh_info

__all__ = [
    "load_kb", "save_kb", "add_entry", "delete_entry", "update_entry",
    "match_knowledge", "set_ssh_info",
    "KBEntry", "CATEGORIES",
]
