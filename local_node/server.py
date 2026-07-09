# -*- coding: utf-8 -*-
"""
local_node/server.py — REST 协议层（B 站 RPA + Etsy API 本地节点）

【干什么用？】
  在本机 8001 端口启动 Web 服务，云端 Agent 经 Cloudflare Tunnel / 本机 HTTP 调用本地工具。

【路由】
  - /api/get_up_list 等 — B 站 RPA（rpa_tools）
  - /api/etsy_*         — Etsy 评论（etsy_agent/etsy_tools）
"""

import os
import sys
from typing import Any, Literal, Optional

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
from etsy_agent.etsy_tools import (
    tool_etsy_check_credentials,
    tool_etsy_fetch_and_export_reviews,
    tool_etsy_fetch_listing_reviews,
    tool_etsy_write_reviews_excel,
)

app = FastAPI(
    title="SmartAgents 本地节点 API",
    description="B 站 RPA + Etsy 评论（P0 统一 envelope）",
    version="2.1.0",
)


def _raise_envelope(result: dict, *, unavailable_codes: frozenset[str] = frozenset()) -> dict:
    if result.get("ok"):
        return result
    code = (result.get("error") or {}).get("code", "")
    status = 503 if code in unavailable_codes else 400
    raise HTTPException(status_code=status, detail=result)


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
        status_code = 400
        if result["error"]["code"] == "LOGIN_STATE_MISSING":
            status_code = 503
        raise HTTPException(status_code=status_code, detail=result)
    return result


# ---------------------------------------------------------------------------
# Etsy — REST 路由（etsy_agent/etsy_tools）
# ---------------------------------------------------------------------------

class EtsyFetchReviewsRequest(BaseModel):
    listing_id: str
    listing_url: Optional[str] = None
    limit: int = 25
    max_pages: int = 5
    min_created: Optional[int] = None
    max_created: Optional[int] = None
    dry_run: bool = False


class EtsyWriteReviewsRequest(BaseModel):
    listing_id: str
    reviews: list[dict[str, Any]]
    listing_url: Optional[str] = None
    excel_path: Optional[str] = None
    sheet_name: str = "评论明细"
    deduplicate: bool = True


class EtsyFetchExportRequest(BaseModel):
    listing_url_or_id: str
    limit: int = 25
    max_pages: int = 5
    min_created: Optional[int] = None
    max_created: Optional[int] = None
    excel_path: Optional[str] = None
    dry_run: bool = False


@app.get("/api/etsy_check_credentials", summary="检查 Etsy API 凭证（P0 envelope）")
def api_etsy_check_credentials(
    probe: bool = Query(False),
    probe_listing_id: str = Query("786582119"),
):
    result = tool_etsy_check_credentials(probe=probe, probe_listing_id=probe_listing_id)
    return _raise_envelope(result, unavailable_codes=frozenset({"ETSY_API_KEY_MISSING"}))


@app.post("/api/etsy_fetch_listing_reviews", summary="拉取 Etsy listing 评论（P0 envelope）")
def api_etsy_fetch_listing_reviews(req: EtsyFetchReviewsRequest):
    result = tool_etsy_fetch_listing_reviews(
        req.listing_id,
        listing_url=req.listing_url,
        limit=req.limit,
        max_pages=req.max_pages,
        min_created=req.min_created,
        max_created=req.max_created,
        dry_run=req.dry_run,
    )
    return _raise_envelope(result, unavailable_codes=frozenset({"ETSY_API_KEY_MISSING"}))


@app.post("/api/etsy_write_reviews_excel", summary="Etsy 评论写入 Excel（P0 envelope）")
def api_etsy_write_reviews_excel(req: EtsyWriteReviewsRequest):
    result = tool_etsy_write_reviews_excel(
        req.listing_id,
        req.reviews,
        listing_url=req.listing_url,
        excel_path=req.excel_path,
        sheet_name=req.sheet_name,
        deduplicate=req.deduplicate,
    )
    return _raise_envelope(result)


@app.post("/api/etsy_fetch_and_export_reviews", summary="Etsy 拉取并导出评论（P0 envelope）")
def api_etsy_fetch_and_export_reviews(req: EtsyFetchExportRequest):
    result = tool_etsy_fetch_and_export_reviews(
        req.listing_url_or_id,
        limit=req.limit,
        max_pages=req.max_pages,
        min_created=req.min_created,
        max_created=req.max_created,
        excel_path=req.excel_path,
        dry_run=req.dry_run,
    )
    return _raise_envelope(result, unavailable_codes=frozenset({"ETSY_API_KEY_MISSING"}))


# ---------------------------------------------------------------------------
# 直接运行此文件时：启动 uvicorn Web 服务器，监听 0.0.0.0:8001
# ---------------------------------------------------------------------------
# 0.0.0.0 表示接受本机及局域网/隧道转发的连接（不仅是 127.0.0.1）
if __name__ == "__main__":
    print("🚀 正在启动本地节点服务器 (B站 RPA + Etsy API, P0 envelope v2.1)...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
