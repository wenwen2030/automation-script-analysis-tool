"""监控核心函数：日志轮询、文件查找、监控模式主循环"""

import os
import time
import paramiko

from ..config import FINISH_PATTERN, POLL_INTERVAL, IGNORE_FILES, STALL_TIMEOUT, ERROR_PATTERNS
from ..utils import show_popup


def find_latest_log(client, monitor_dir):
    """自动查找用户目录下最新的 .txt 日志文件"""
    cmd = (
        f"find {monitor_dir} -maxdepth 2 -name '*.txt' "
        f"-newer {monitor_dir} -mmin -60 -type f "
        f"2>/dev/null | xargs ls -t 2>/dev/null | head -5"
    )
    stdin, stdout, stderr = client.exec_command(cmd)
    files = stdout.read().decode().strip().split('\n')
    files = [f for f in files if f.strip()]

    if not files:
        cmd2 = f"find {monitor_dir} -maxdepth 2 -name '*.txt' -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -5"
        stdin, stdout, stderr = client.exec_command(cmd2)
        files = stdout.read().decode().strip().split('\n')
        files = [f for f in files if f.strip()]

    files = [f for f in files if os.path.basename(f) not in IGNORE_FILES]
    return files


def monitor(log_file, host, user, password, stop_event=None, log_fn=None,
            process_keyword=None):
    """轮询监控指定日志文件，返回结果字符串或 None。
    
    log_fn: 日志输出回调，签名 log_fn(msg, tag="info")。默认用 print。
    process_keyword: 用于 pgrep 检测进程是否存活的关键词。
    """
    if log_fn is None:
        log_fn = lambda msg, tag="info": print(msg)

    log_fn(f"连接 {host} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password)
    log_fn(f"已连接，监控文件: {log_file}")
    log_fn(f"每 {POLL_INTERVAL} 秒检查一次")

    last_line_count = 0
    waiting_for_file = True
    last_change_time = time.time()
    process_dead_since = None  # 进程消失的时间点
    try:
        while True:
            if stop_event and stop_event.is_set():
                log_fn("收到停止信号", "error")
                client.close()
                return None

            _, stdout_check, _ = client.exec_command(f"test -f '{log_file}' && echo EXISTS || echo MISSING")
            file_status = stdout_check.read().decode().strip()

            if file_status != "EXISTS":
                if waiting_for_file:
                    log_fn(f"  [{time.strftime('%H:%M:%S')}] 等待日志文件创建...")
                time.sleep(POLL_INTERVAL)
                continue

            if waiting_for_file:
                log_fn(f"  [{time.strftime('%H:%M:%S')}] 日志文件已创建，开始追踪...", "highlight")
                waiting_for_file = False
                last_change_time = time.time()

            _, stdout_wc, _ = client.exec_command(f"wc -l < '{log_file}' 2>/dev/null")
            wc_str = stdout_wc.read().decode().strip()
            cur_lines = int(wc_str) if wc_str.isdigit() else 0

            if cur_lines > last_line_count:
                new_count = cur_lines - last_line_count
                _, stdout_new, _ = client.exec_command(
                    f"tail -n {new_count} '{log_file}' 2>/dev/null"
                )
                new_output = stdout_new.read().decode("utf-8", errors="replace")
                if new_output.strip():
                    for line in new_output.splitlines():
                        log_fn(f"  | {line}")

                    # 检测致命错误关键词
                    for pattern in ERROR_PATTERNS:
                        if pattern in new_output:
                            log_fn(f">>> 检测到致命错误: {pattern}", "error")
                            client.close()
                            return "errScript"

                last_line_count = cur_lines
                last_change_time = time.time()
                process_dead_since = None  # 日志有更新，重置进程死亡计时
            else:
                stall_secs = int(time.time() - last_change_time)
                log_fn(f"  [{time.strftime('%H:%M:%S')}] ({cur_lines} 行) 脚本运行中... (无变化 {stall_secs}s)")

                # 检测远程进程是否还活着
                if process_keyword and stall_secs >= 30:
                    _, stdout_pg, _ = client.exec_command(f"pgrep -f '{process_keyword}' 2>/dev/null")
                    pids = stdout_pg.read().decode().strip()
                    if not pids:
                        if process_dead_since is None:
                            process_dead_since = time.time()
                            log_fn(f"  [{time.strftime('%H:%M:%S')}] 远程进程已消失，等待确认...", "error")
                        elif time.time() - process_dead_since >= 30:
                            log_fn(f">>> 远程进程已不存在且日志无结束标志，判定异常", "error")
                            client.close()
                            return "stall"
                    else:
                        process_dead_since = None  # 进程还在，重置

                # 兜底超时
                if stall_secs >= STALL_TIMEOUT:
                    log_fn(f">>> 日志无变化超过 {STALL_TIMEOUT} 秒，判定异常（兜底）", "error")
                    client.close()
                    return "stall"

            _, stdout_tail, _ = client.exec_command(f"tail -n 5 '{log_file}' 2>/dev/null")
            tail_output = stdout_tail.read().decode("utf-8", errors="replace")
            match = FINISH_PATTERN.search(tail_output)
            if match:
                result = match.group(1)
                tag = "success" if result.lower() == "pass" else "error"
                log_fn(f">>> 脚本执行完毕，结果: {result.upper()}", tag)
                client.close()
                return result

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        log_fn("手动中断", "error")
        client.close()
        return None


def find_new_log(client, finished_logs, monitor_dir):
    """查找最新的、还没监控过且尚未完成的日志文件"""
    files = find_latest_log(client, monitor_dir)
    for f in files:
        if f in finished_logs:
            continue
        _, stdout, _ = client.exec_command(f"tail -n 5 '{f}' 2>/dev/null")
        tail_output = stdout.read().decode("utf-8", errors="replace")
        if FINISH_PATTERN.search(tail_output):
            finished_logs.add(f)
            continue
        return f
    return None


def main_monitor(host, user, password, monitor_dir, popup_enabled):
    """监控模式主循环"""
    finished_logs = set()
    print(f"=== 测试脚本监控工具 (监控模式) ===")
    print(f"服务器: {host}")
    print(f"持续运行中，Ctrl+C 退出\n")

    while True:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, username=user, password=password)

            log_file = find_new_log(client, finished_logs, monitor_dir)
            client.close()

            if not log_file:
                print(f"  [{time.strftime('%H:%M:%S')}] 等待新的测试脚本启动...")
                time.sleep(POLL_INTERVAL)
                continue

            print(f"\n发现新日志: {log_file}")
            result = monitor(log_file, host, user, password)

            if result:
                if popup_enabled:
                    show_popup(result)
                finished_logs.add(log_file)
                print(f"\n继续监控下一个脚本...\n")
            else:
                break

        except KeyboardInterrupt:
            print("\n手动退出监控")
            break
        except Exception as e:
            print(f"  连接异常: {e}，10秒后重试...")
            time.sleep(10)
