"""脚本文件索引：后台建索引缓存，加速tcl文件查找"""

import os
import re
import threading
import time
import logging

from ..config import SCRIPT_SEARCH_DIRS

logger = logging.getLogger(__name__)

# 全局索引实例
_index = None
_index_lock = threading.Lock()


class ScriptIndex:
    """脚本名 → 文件路径 的索引缓存"""

    def __init__(self, search_dirs=None):
        self.search_dirs = search_dirs or SCRIPT_SEARCH_DIRS
        # {script_name_lower: file_path}  精确索引
        self._exact_map = {}
        # {filename_lower: file_path}  全文件名索引（用于模糊匹配）
        self._file_map = {}
        self._ready = False
        self._building = False
        self._build_time = 0

    @property
    def ready(self):
        return self._ready

    def build(self):
        """同步建索引（耗时操作，应在后台线程调用）"""
        if self._building:
            return
        self._building = True
        t0 = time.time()
        exact_map = {}
        file_map = {}

        for search_dir in self.search_dirs:
            try:
                if not os.path.isdir(search_dir):
                    continue
            except OSError:
                continue

            for root, _, files in os.walk(search_dir):
                for f in files:
                    if not f.lower().endswith(".tcl"):
                        continue
                    full_path = os.path.join(root, f)
                    f_lower = f.lower()
                    file_map[f_lower] = full_path

                    # 提取脚本名（去掉.tcl和pica8前缀）
                    name = f[:-4]  # 去掉 .tcl
                    name_lower = name.lower()
                    if name_lower.startswith("pica8"):
                        core_name = name[5:]  # 去掉 pica8 前缀
                        exact_map[core_name.lower()] = full_path
                    exact_map[name_lower] = full_path

        self._exact_map = exact_map
        self._file_map = file_map
        self._build_time = time.time() - t0
        self._ready = True
        self._building = False
        logger.info(f"脚本索引建立完成: {len(exact_map)} 条, 耗时 {self._build_time:.1f}s")

    def build_async(self, callback=None):
        """异步建索引"""
        def _worker():
            self.build()
            if callback:
                callback()
        threading.Thread(target=_worker, daemon=True).start()

    def find(self, script_name):
        """从索引中查找脚本路径，返回路径或None"""
        if not self._ready:
            return None
        name_lower = script_name.lower()

        # 1. 精确匹配
        if name_lower in self._exact_map:
            return self._exact_map[name_lower]

        # 2. 带pica8前缀匹配
        pica8_name = f"pica8{name_lower}"
        if pica8_name in self._exact_map:
            return self._exact_map[pica8_name]

        # 3. 文件名包含脚本名
        for fname, fpath in self._file_map.items():
            if name_lower in fname:
                return fpath

        # 4. feature名模糊匹配（去掉_XX_XX后缀）
        feature_match = re.match(r"(.+?)_\d+_\d+$", script_name)
        if feature_match:
            feature = feature_match.group(1).lower()
            for fname, fpath in self._file_map.items():
                if feature in fname:
                    return fpath

        return None

    def refresh(self):
        """刷新索引"""
        self._ready = False
        self.build_async()


def get_index():
    """获取全局索引实例（单例）"""
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = ScriptIndex()
    return _index


def find_script_cached(script_name):
    """优先用索引查找，索引未就绪则返回None"""
    idx = get_index()
    if idx.ready:
        return idx.find(script_name)
    return None


def find_script_fallback(script_name):
    """兜底搜索：按优先级遍历多个目录（方案3）"""
    for search_dir in SCRIPT_SEARCH_DIRS:
        result = _walk_search(script_name, search_dir)
        if result:
            return result
    return None


def _walk_search(script_name, search_dir):
    """在单个目录中递归搜索脚本文件"""
    try:
        if not os.path.isdir(search_dir):
            return None
    except OSError:
        return None

    candidates = [
        f"pica8{script_name}.tcl".lower(),
        f"{script_name}.tcl".lower(),
    ]

    feature_match = re.match(r"(.+?)_\d+_\d+$", script_name)
    feature_name = feature_match.group(1).lower() if feature_match else script_name.lower()

    found_contains = None
    found_feature = None

    for root, _, files in os.walk(search_dir):
        for f in files:
            if not f.lower().endswith(".tcl"):
                continue
            f_lower = f.lower()
            # 精确匹配
            if f_lower in candidates:
                return os.path.join(root, f)
            # 包含脚本名
            if script_name.lower() in f_lower and found_contains is None:
                found_contains = os.path.join(root, f)
            # 包含feature名
            elif feature_name in f_lower and found_feature is None:
                found_feature = os.path.join(root, f)

    return found_contains or found_feature


def find_script(script_name):
    """统一入口：索引可用时O(1)查找，否则兜底遍历"""
    # 先尝试索引
    result = find_script_cached(script_name)
    if result:
        return result
    # 索引未就绪，兜底遍历
    return find_script_fallback(script_name)
