"""
测试脚本监控工具入口

用法: python -m monitor_tool
"""

import sys

from .login_dialog import show_login
from .monitor_panel import MonitorPanel
from .batch_panel import BatchControlPanel
from .analysis.script_index import get_index
from .updater import check_update


def main():
    # 启动时异步建立脚本索引（不阻塞UI）
    get_index().build_async()

    pending_scripts = None

    while True:
        params = show_login(initial_scripts=pending_scripts)
        if params is None:
            sys.exit()

        if params["mode"] == "monitor":
            panel = MonitorPanel(
                params["host"], params["user"], params["password"],
                params["monitor_dir"], params["popup"],
            )
            panel.run()
            if panel.go_back:
                continue
            break
        else:
            panel = BatchControlPanel(
                host=params["host"],
                user=params["user"],
                password=params["password"],
                monitor_dir=params["monitor_dir"],
                popup_enabled=params["popup"],
                automation_cmd=params["automation_cmd"],
                dut_name=params["dut_name"],
                initial_scripts=pending_scripts or params["scripts"],
                dut_ip=params.get("dut_ip", ""),
                dut_user=params.get("dut_user", "admin"),
                dut_pass=params.get("dut_pass", "pica8"),
                max_retry=params.get("max_retry", 3),
                dut_devices=params.get("dut_devices", []),
            )
            panel.run()
            if panel.go_back:
                pending_scripts = panel.current_scripts
                continue
            break


if __name__ == "__main__":
    main()
