# -*- coding: utf-8 -*-
"""
mcp_server/run_sync.py — 在「独立子进程」里执行 fetch_fans_data（真 RPA）

【为什么需要这个文件？】
  bilibili_mcp.py 运行在 asyncio 事件循环中；
  main.get_up_fans_data 使用 Playwright「同步」API，直接在 async 里调用会冲突。
  解决办法：MCP 父进程 spawn 本子进程，子进程里同步跑完 RPA，把 envelope JSON 打印到 stdout。

【谁调用它？】
  bilibili_mcp.py 的 fetch_fans_data（dry_run=false 时）：
    python run_sync.py "UP主名"

【输出格式】
  ===RESULT_START===
  { ... envelope JSON ... }
  ===RESULT_END===
  父进程从 stdout 里截取这两行之间的 JSON 解析后返回给 Cursor/Agent。
"""

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpa_tools import tool_fetch_fans_data

if __name__ == "__main__":
    # 支持可选 flag：python run_sync.py --dry-run "老番茄"
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[1:]

    if not args:
        print("===RESULT_START===")
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": "INVALID_INPUT", "message": "missing up_name"},
                }
            )
        )
        print("===RESULT_END===")
        sys.exit(1)

    up_name = args[0]
    # 调用 rpa_tools（内部会调 main.get_up_fans_data 或 dry_run 分支）
    result = tool_fetch_fans_data(up_name, dry_run=dry_run)

    print("===RESULT_START===")
    print(json.dumps(result, ensure_ascii=False))
    print("===RESULT_END===")
