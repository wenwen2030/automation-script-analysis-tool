"""SSH 公共工具 — 统一连接池和常用操作"""

import threading
import time
import paramiko

# 全局 SSH 连接池
_SSH_POOL = {}
_SSH_LOCK = threading.Lock()
_SSH_IDLE_TIMEOUT = 60


def get_ssh_client(host, user, password, timeout=10):
    """获取/创建 SSH 连接(缓存复用)

    Args:
        host: 远程主机地址
        user: SSH 用户名
        password: SSH 密码
        timeout: 连接超时(秒)

    Returns:
        paramiko.SSHClient 实例
    """
    key = (host, user)
    with _SSH_LOCK:
        if key in _SSH_POOL:
            client, _ = _SSH_POOL[key]
            try:
                transport = client.get_transport()
                if transport and transport.is_active():
                    _SSH_POOL[key] = (client, time.time())
                    return client
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            del _SSH_POOL[key]

        # 新建连接
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=timeout,
                       look_for_keys=False, allow_agent=False, banner_timeout=10)
        _SSH_POOL[key] = (client, time.time())
        return client


def ssh_exec(host, user, password, command, timeout=30):
    """执行单条SSH命令并返回输出

    Args:
        host: 远程主机地址
        user: SSH 用户名
        password: SSH 密码
        command: 要执行的命令
        timeout: 命令超时(秒)

    Returns:
        (stdout_str, stderr_str) 元组
    """
    client = get_ssh_client(host, user, password)
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    return (
        stdout.read().decode("utf-8", errors="replace"),
        stderr.read().decode("utf-8", errors="replace"),
    )


def close_all_ssh():
    """关闭所有缓存的SSH连接"""
    with _SSH_LOCK:
        for key, (client, _) in list(_SSH_POOL.items()):
            try:
                client.close()
            except Exception:
                pass
        _SSH_POOL.clear()
