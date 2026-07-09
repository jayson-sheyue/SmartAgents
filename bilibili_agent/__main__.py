# -*- coding: utf-8 -*-
"""python -m bilibili_agent login"""

from __future__ import annotations

import sys

from bilibili_agent.bilibili_tools import manual_login

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        manual_login()
    else:
        print("用法:")
        print("  python -m bilibili_agent login   # 保存 bilibili_state.json")
        print("  ./scripts/run_adk_bilibili_agent.sh   # ADK Agent 对话")
