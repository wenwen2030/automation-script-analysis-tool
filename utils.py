"""工具函数：弹窗通知、汇总打印"""

import ctypes
import threading


def show_popup(result):
    """Windows 原生弹窗，强制置顶，非阻塞（在独立线程中弹出）"""
    def _popup():
        base_flags = 0x00001000 | 0x00040000 | 0x00010000
        if result.lower() == "pass":
            title = "测试通过 ✓"
            msg = "脚本执行完毕!\n\n结果: PASS"
            flags = base_flags | 0x00000040
        else:
            title = "测试失败 ✗"
            msg = f"脚本执行完毕!\n\n结果: {result.upper()}"
            flags = base_flags | 0x00000030
        ctypes.windll.user32.MessageBoxW(0, msg, title, flags)
    threading.Thread(target=_popup, daemon=True).start()


def print_summary(summary):
    """打印批量执行汇总"""
    print(f"\n\n{'='*60}")
    print(f"{'批量执行汇总':^52}")
    print(f"{'='*60}")
    print(f"{'序号':<5} {'脚本名':<35} {'结果':<10} {'次数':<5}")
    print(f"{'-'*60}")

    pass_count = 0
    fail_count = 0
    for i, (name, result, attempts) in enumerate(summary, 1):
        print(f"{i:<5} {name:<35} {result:<10} {attempts:<5}")
        if result == "PASS":
            pass_count += 1
        else:
            fail_count += 1

    print(f"{'-'*60}")
    print(f"总计: {len(summary)} 个脚本，PASS: {pass_count}，其他: {fail_count}")
    print(f"{'='*60}")
