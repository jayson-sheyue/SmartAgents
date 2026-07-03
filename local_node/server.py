# -*- coding: utf-8 -*-
"""
local_node/server.py — REST 协议层（把 rpa_tools 暴露成 HTTP API）

【干什么用？】
  在本机 8001 端口启动一个 Web 服务，云端 REST Agent 或 curl 可以通过 HTTP 调用 RPA。

【和 MCP 的区别】
  - 本文件：REST，URL 如 GET /api/get_up_list
  - mcp_server/bilibili_mcp.py：MCP 协议，给 Cursor / 云端 MCP Agent 用

【响应格式】
  直接返回 rpa_tools 的 envelope JSON（不再包一层 {status, data} 旧格式）。

【怎么启动？】
  python local_node/server.py
  或项目根目录：python server.py（兼容 shim，内部转调本文件）
"""

import os
import sys
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# 修复 import 路径
# ---------------------------------------------------------------------------
# 若你在 local_node/ 目录下执行 python server.py，Python 默认只把 local_node 加入搜索路径，
# 找不到项目根目录的 rpa_tools.py。下面两行把「上一级目录（项目根）」插到最前面。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn

from rpa_tools import tool_fetch_fans_data, tool_get_up_list, tool_write_excel

# FastAPI：用来写 REST API 的框架（类似「自动帮你解析 HTTP 请求的小服务器」）
app = FastAPI(
    title="B站 RPA 本地节点 API",
    description="供 Agent 调用的本地 RPA 接口（P0 统一 envelope）",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# POST 请求体的数据结构（Pydantic 会自动校验 JSON 字段）
# ---------------------------------------------------------------------------

class FetchFansRequest(BaseModel):
    """POST /api/fetch_fans_data 的 JSON body 长什么样。"""
    up_name: str
    dry_run: bool = False  # 默认 false = 真要抓；true = 只检查登录态


class WriteExcelRequest(BaseModel):
    """POST /api/write_excel 的 JSON body。"""
    up_name: str
    fans_count: str
    excel_path: Optional[str] = None
    sheet_name: str = "Sheet1"
    target_column: str = "粉丝数"
    write_mode: Literal["update", "append_if_missing"] = "update"


# ---------------------------------------------------------------------------
# 路由 1：GET 读名单（参数在 URL ?excel_path=... 里，叫 query string）
# ---------------------------------------------------------------------------

@app.get("/api/get_up_list", summary="读取本地 Excel 获取 UP 主名单（P0 envelope）")
def api_get_list(
    excel_path: Optional[str] = Query(None, description="Excel 绝对或 ~/ 路径"),
    sheet_name: str = Query("Sheet1"),
    name_column: Optional[str] = Query(None, description="UP 主列名，默认第一列"),
    limit: Optional[int] = Query(None, ge=1, description="最多返回条数"),
):
    # 真正干活的是 rpa_tools，这里只做「HTTP 入口 → 调函数 → 返回 JSON」
    result = tool_get_up_list(
        excel_path=excel_path,
        sheet_name=sheet_name,
        name_column=name_column,
        limit=limit,
    )
    if not result["ok"]:
        # 失败时 HTTP 状态码 400，body 仍是完整 envelope（在 detail 里）
        raise HTTPException(status_code=400, detail=result)
    return result


# ---------------------------------------------------------------------------
# 路由 2：POST 抓取粉丝数
# ---------------------------------------------------------------------------

@app.post("/api/fetch_fans_data", summary="启动本地浏览器抓取粉丝数（P0 envelope）")
def api_fetch_fans(req: FetchFansRequest):
    result = tool_fetch_fans_data(up_name=req.up_name, dry_run=req.dry_run)
    status_code = 200 if result["ok"] else 400
    # 登录态缺失用 503（服务暂不可用），便于区分「参数错」和「环境没准备好」
    if not result["ok"] and result["error"]["code"] == "LOGIN_STATE_MISSING":
        status_code = 503
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result)
    return result


# ---------------------------------------------------------------------------
# 路由 3：POST 写 Excel
# ---------------------------------------------------------------------------

@app.post("/api/write_excel", summary="将粉丝数写回 Excel（P0 envelope）")
def api_write_excel(req: WriteExcelRequest):
    result = tool_write_excel(
        up_name=req.up_name,
        fans_count=req.fans_count,
        excel_path=req.excel_path,
        sheet_name=req.sheet_name,
        target_column=req.target_column,
        write_mode=req.write_mode,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result)
    return result


# ---------------------------------------------------------------------------
# 直接运行此文件时：启动 uvicorn Web 服务器，监听 0.0.0.0:8001
# ---------------------------------------------------------------------------
# 0.0.0.0 表示接受本机及局域网/ngrok 转发的连接（不仅是 127.0.0.1）
if __name__ == "__main__":
    print("🚀 正在启动本地 RPA 节点服务器 (P0 envelope API v2)...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
