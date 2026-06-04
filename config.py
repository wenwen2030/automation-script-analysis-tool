"""常量和默认配置"""

import re

# 脚本结束标志
FINISH_PATTERN = re.compile(r"script finished:\s*(pass|fail|errScript\w+)", re.IGNORECASE)
POLL_INTERVAL = 5
MAX_RETRY = 3

# 忽略的文件名
IGNORE_FILES = {"TestCases.txt"}

# 脚本卡住检测：日志行数连续不变超过此时间（秒）则判定卡住（兜底）
STALL_TIMEOUT = 360

# 脚本致命错误关键词：日志中出现这些内容则立即判定脚本异常
ERROR_PATTERNS = [
    "errScriptAborted",
    "errDeviceDied",
]

# 登录界面默认值
DEFAULT_HOST = "10.28.165.18"
DEFAULT_USER = "Ableson.Niu"
DEFAULT_PASS = "admin@fs123"
DEFAULT_DIR = "/home/Ableson.Niu/N8550-64C_Q2_main_P0P1P2_1/"
DEFAULT_AUTOMATION_CMD = "../automation/ws"
DEFAULT_DUT_NAME = "N8550-64C_DUT7"
DEFAULT_DUT_IP = ""
DEFAULT_DUT_USER = "admin"
DEFAULT_DUT_PASS = "pica8"
