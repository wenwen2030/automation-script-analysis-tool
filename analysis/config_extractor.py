"""从脚本日志中按 Step 提取下发的 PicOS 配置命令

匹配规则：
- 识别 pInfo "::Step X 描述" 作为 Step 边界
- 在每个 Step 范围内找出 admin@PICOS# / admin@PICOS> 行后的命令
- 关注 set / delete / commit / run / show 等关键词

输出格式类似:
  Step 1: DUT hash configure
  >>> [PICOS] <<<
  set interface aggregate-ethernet ae1
  ...
  commit
"""

import re

STEP_LOG_RE = re.compile(r":*Step\s*([\d.]+)\s*[:：\-]?\s*(.+)", re.I)

# 提示符行：admin@PICOS# 或 admin@PICOS>
PROMPT_RE = re.compile(r"admin@\w+[#>$]\s*(.*)$")

# 关注的命令前缀
CMD_PREFIXES = ("set ", "delete ", "commit", "run ", "show ", "configure",
                "edit ", "exit", "rollback", "load", "save")


def extract_configs_by_step(log_text):
    """按 Step 提取配置命令

    返回: [{"step_no": "1", "step_desc": "xxx", "commands": [cmd1, cmd2, ...]}, ...]
    """
    lines = log_text.splitlines()
    steps = []
    current_step = None

    for line in lines:
        # 检测 Step 行
        step_m = STEP_LOG_RE.search(line)
        if step_m and "pInfo" not in line and not _looks_like_command(line):
            # 是日志输出里的 step 提示
            if current_step is not None:
                steps.append(current_step)
            current_step = {
                "step_no": step_m.group(1).strip(),
                "step_desc": step_m.group(2).strip(),
                "commands": [],
            }
            continue

        # 提取提示符后面的命令
        prompt_m = PROMPT_RE.search(line)
        if prompt_m:
            cmd = prompt_m.group(1).strip()
            if cmd and _is_relevant_cmd(cmd):
                if current_step is None:
                    current_step = {
                        "step_no": "0",
                        "step_desc": "(初始化)",
                        "commands": [],
                    }
                # 去重（连续重复的）
                if not current_step["commands"] or current_step["commands"][-1] != cmd:
                    current_step["commands"].append(cmd)

    if current_step is not None:
        steps.append(current_step)

    # 过滤掉没有命令的 step
    steps = [s for s in steps if s["commands"]]
    return steps


def _is_relevant_cmd(cmd):
    """判断是否是关心的配置/操作命令"""
    cmd_low = cmd.lstrip()
    for prefix in CMD_PREFIXES:
        if cmd_low.startswith(prefix):
            return True
    return False


def _looks_like_command(line):
    """判断这一行像命令而不是 step 描述（用来排除误匹配）"""
    if any(line.lstrip().startswith(p) for p in ("set ", "delete ", "commit", "run ")):
        return True
    return False


def format_steps_for_display(steps):
    """格式化为类似图片那样的展示文本"""
    parts = []
    for s in steps:
        parts.append("=" * 80)
        parts.append(f"Step {s['step_no']}: {s['step_desc']}")
        parts.append("=" * 80)
        parts.append(">>> [PICOS] <<<")
        for cmd in s["commands"]:
            parts.append(cmd)
        parts.append("")
    return "\n".join(parts)
