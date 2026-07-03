# -*- coding: utf-8 -*-
"""
mcp_server/bilibili_mcp.py — MCP 协议层（把 rpa_tools 暴露成 MCP Tools）

【MCP 是什么？】
  Model Context Protocol：大模型客户端（如 Cursor）和「工具服务器」之间的标准通信协议。
  本文件就是「B 站 RPA 工具服务器」。

【两种运行模式】（看启动时有没有 --http）

  1) 不加 --http（默认）—— stdio 模式
     - Cursor 通过 .cursor/mcp.json 启动：python mcp_server/bilibili_mcp.py
     - 通过「标准输入/输出管道」传 JSON-RPC，不走网络
     - **不需要 ngrok**，本机进程间通信

  2) 加 --http —— HTTP 模式
     - python mcp_server/bilibili_mcp.py --http
     - 监听 8002 端口，供云端 cloud_agent_mcp + ngrok 调用

【和 REST 的关系】
  三个工具（get_up_list / fetch_fans_data / write_excel）参数与 rpa_tools 一致；
  本文件 mostly 是「薄包装」，真正逻辑在 rpa_tools.py。
"""

import sys
import os
from typing import Any, Literal, Optional

# 把项目根目录加入 path，以便 import rpa_tools、读取 .env
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from rpa_tools import tool_fetch_fans_data, tool_get_up_list, tool_write_excel

load_dotenv()  # 读取项目根目录 .env（如 NGROK_HOST）

# ngrok 免费域名（不含 https://），HTTP 模式时用于 Host 白名单，否则云端请求会被 421 拒绝
NGROK_HOST = os.getenv("NGROK_HOST", "")

# 创建 MCP 服务器实例；名字会显示在 Cursor 的 MCP 列表里
mcp = FastMCP("Bilibili RPA MCP Server")


# =============================================================================
# MCP Tool 1：get_up_list
# =============================================================================
# @mcp.tool() 装饰器：把下面这个 Python 函数注册成 Agent 可调用的「工具」
# 函数的 docstring 和参数类型会展示给大模型，帮助它决定何时调用、传什么参数

@mcp.tool()
def get_up_list(
    excel_path: Optional[str] = None,
    sheet_name: str = "Sheet1",
    name_column: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """读取本地 Excel，返回 UP 主名单（P0 统一 envelope）。

    Args:
        excel_path: Excel 路径，默认 ~/Desktop/Up主名称.xlsx；须在 Desktop 或 ~/Documents/BilibiliRPA 下
        sheet_name: 工作表名，默认 Sheet1
        name_column: UP 主列名，默认第一列
        limit: 最多返回条数

    Returns:
        ok/data/error/meta 结构；成功时读 data.up_names
    """
    return tool_get_up_list(
        excel_path=excel_path,
        sheet_name=sheet_name,
        name_column=name_column,
        limit=limit,
    )


# =============================================================================
# MCP Tool 2：fetch_fans_data
# =============================================================================
# 注意：必须是 async，因为 MCP 运行在 asyncio 事件循环里。
# Playwright 同步 API 不能直接在 async 里跑，所以真抓取时启动子进程 run_sync.py。

@mcp.tool()
async def fetch_fans_data(up_name: str, dry_run: bool = False) -> dict[str, Any]:
    """抓取指定 UP 主粉丝数（P0 统一 envelope）。

    Args:
        up_name: UP 主名称
        dry_run: True 时仅检查登录态，不启动浏览器

    Returns:
        成功时 data.fans_count_display 可用于 write_excel
    """
    import asyncio
    import json

    # dry_run 不涉及浏览器，直接调 rpa_tools 即可
    if dry_run:
        return tool_fetch_fans_data(up_name=up_name, dry_run=True)

    # --- 真抓取：子进程跑 run_sync.py，避免 Playwright 与 asyncio 冲突 ---
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_sync.py")

    process = await asyncio.create_subprocess_exec(
        sys.executable,  # 当前 venv 的 python
        script_path,
        up_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8")

    # run_sync.py 用 ===RESULT_START/END=== 包裹 JSON，便于从混合日志里截取
    if "===RESULT_START===" in output and "===RESULT_END===" in output:
        json_str = output.split("===RESULT_START===")[1].split("===RESULT_END===")[0].strip()
        try:
            return json.loads(json_str)  # 已是完整 envelope
        except json.JSONDecodeError:
            pass

    # 子进程异常或未按约定输出时的兜底失败 envelope
    return {
        "ok": False,
        "tool": "fetch_fans_data",
        "data": {"up_name": up_name, "status": "failed"},
        "error": {
            "code": "FETCH_FAILED",
            "message": stderr.decode("utf-8") or "子进程未返回预期格式",
            "retryable": True,
        },
        "meta": {},
    }


# =============================================================================
# MCP Tool 3：write_excel
# =============================================================================

@mcp.tool()
def write_excel(
    up_name: str,
    fans_count: str,
    excel_path: Optional[str] = None,
    sheet_name: str = "Sheet1",
    target_column: str = "粉丝数",
    write_mode: Literal["update", "append_if_missing"] = "update",
) -> dict[str, Any]:
    """写回 Excel（P0 统一 envelope）。

    Args:
        up_name: UP 主名称
        fans_count: 建议使用 fetch 返回的 fans_count_display
        excel_path: 目标 Excel
        sheet_name: 工作表名
        target_column: 写入列名
        write_mode: update 或 append_if_missing
    """
    return tool_write_excel(
        up_name=up_name,
        fans_count=fans_count,
        excel_path=excel_path,
        sheet_name=sheet_name,
        target_column=target_column,
        write_mode=write_mode,
    )


# =============================================================================
# 程序入口：根据命令行决定 stdio 还是 HTTP
# =============================================================================

if __name__ == "__main__":
    if "--http" in sys.argv:
        # HTTP 模式：给云端 Agent + ngrok 用
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = 8002
        # FastMCP 默认只允许 localhost Host；ngrok 转发时 Host 是公网域名，必须加白名单
        allowed_hosts = [
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ]
        allowed_origins = [
            "http://127.0.0.1:*",
            "http://localhost:*",
        ]
        if NGROK_HOST:
            allowed_hosts.extend([NGROK_HOST, f"{NGROK_HOST}:*"])
            allowed_origins.append(f"https://{NGROK_HOST}")
        else:
            print("⚠️ 未配置 NGROK_HOST，云端经 ngrok 访问可能报 421 Invalid Host")
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
        mcp.run(transport="streamable-http")
    else:
        # stdio 模式：Cursor 默认走这条，无 --http
        mcp.run()
