import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from vertexai.agent_engines import AdkApp

# 导入本地定义好的云端 Agent 大脑
from cloud_agent import cloud_agent

app = FastAPI()

# 允许前端跨域请求 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_id: str

# 初始化本地的 AdkApp，它提供了完整的对话和状态管理功能
adk_app = AdkApp(agent=cloud_agent)

@app.post("/chat")
async def chat_with_agent(req: ChatRequest):
    print(f"收到前端消息: [User: {req.user_id}, Session: {req.session_id}] {req.message}")
    
    try:
        # 为了能够在本地保存记忆，我们先确保 Session 存在
        try:
            session = await adk_app.async_get_session(user_id=req.user_id, session_id=req.session_id)
        except Exception:
            # 如果没找到，则创建一个新的
            session = await adk_app.async_create_session(user_id=req.user_id, session_id=req.session_id)

        reply_text = ""
        # 本地直接运行 Agent，不需要发起远端 REST API 请求，完美避开云端部署和流式传输的 Bug
        async for event in adk_app.async_stream_query(
            message=req.message, 
            user_id=req.user_id, 
            session_id=req.session_id
        ):
            # 从事件流中提取文本
            if isinstance(event, dict) and "content" in event:
                try:
                    parts = event["content"].get("parts", [])
                    if parts and "text" in parts[0]:
                        reply_text += parts[0]["text"]
                except Exception:
                    pass
            elif hasattr(event, "content"):
                reply_text += event.content

        if not reply_text:
            reply_text = "任务已接收并处理，未收到具体文本回复（请查看控制台日志了解详细过程）。"
            
        return {"reply": reply_text}
    except Exception as e:
        print(f"调用本地 Agent 出错: {e}")
        return {"reply": f"系统开小差了: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    import socket
    import sys

    # Check if port 8001 is open.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8001))
    if result != 0:
        print("本地端口 8001 (本地 API 节点) 未启动，请先运行 python3 server.py")
    sock.close()

    uvicorn.run(app, host="0.0.0.0", port=8000)