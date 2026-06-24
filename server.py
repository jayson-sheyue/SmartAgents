from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import os

# 导入您在 main.py 中写好的 3 个核心技能
from main import read_up_names_from_excel, get_up_fans_data, write_fans_to_excel, get_default_excel_path

app = FastAPI(
    title="B站 RPA 本地节点 API",
    description="供云端 Agent 调用的本地 RPA 接口",
    version="1.0.0"
)

# --- 定义 API 接收的数据格式 ---
class UpNameRequest(BaseModel):
    up_name: str

class WriteDataRequest(BaseModel):
    up_name: str
    fans_count: str

# --- 1. 获取名单接口 ---
@app.get("/api/get_up_list", summary="读取本地 Excel 获取 UP 主名单")
def api_get_list():
    try:
        excel_path = get_default_excel_path()
        names = read_up_names_from_excel(excel_path)
        return {"status": "success", "data": names}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 2. 抓取数据接口 ---
@app.post("/api/fetch_fans_data", summary="启动本地浏览器抓取粉丝数")
def api_fetch_fans(req: UpNameRequest):
    try:
        result = get_up_fans_data(req.up_name)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 3. 写入表格接口 ---
@app.post("/api/write_excel", summary="将粉丝数回写到本地 Excel")
def api_write_excel(req: WriteDataRequest):
    try:
        excel_path = get_default_excel_path()
        write_fans_to_excel(req.up_name, req.fans_count, excel_path)
        return {"status": "success", "message": f"{req.up_name} 数据已写入本地表格。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    print("🚀 正在启动本地 RPA 节点服务器...")
    uvicorn.run(app, host="0.0.0.0", port=8001)