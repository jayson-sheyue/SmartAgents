import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import google.auth
import google.auth.transport.requests

# 配置您的 Google Cloud 项目信息
PROJECT_ID = "webeye-internal-test"
LOCATION = "us-central1"

# 目标云端 Agent 资源 ID
AGENT_RESOURCE_NAME = "projects/839062387451/locations/us-central1/reasoningEngines/6587418803343196160"

app = FastAPI()

# 允许前端跨域请求 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_gcp_token():
    """获取 Google Cloud ADC 认证 Token"""
    import os
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)
    
    credentials, _ = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token

class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_id: str

@app.post("/chat")
def chat_with_agent(req: ChatRequest):
    print(f"收到前端消息: [User: {req.user_id}, Session: {req.session_id}] {req.message}")
    
    try:
        import urllib3
        urllib3.disable_warnings()
        
        # 注意这里使用了 v1beta1 API，这是 Agent Gateway 等新特性通常依赖的端点版本
        url = f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/{AGENT_RESOURCE_NAME}:streamQuery"
        headers = {
            "Authorization": f"Bearer {get_gcp_token()}",
            "Content-Type": "application/json"
        }
        data = {
            "class_method": "async_stream_query",
            "input": {
                "message": req.message,
                "user_id": req.user_id
                # 注意：为了避免云端 Agent 因为找不到前端随机生成的 session_id 而报错，
                # 这里我们暂时不向云端传递 session_id，让云端每次自动创建一个新会话。
            }
        }
        
        reply_text = ""
        response = requests.post(url, headers=headers, json=data, stream=True)
        
        if response.status_code != 200:
            return {"reply": f"云端 Agent 调用失败 (HTTP {response.status_code}): {response.text}"}
            
        for line in response.iter_lines():
            if not line:
                continue
                
            line_str = line.decode('utf-8')
            if line_str.startswith("data: "):
                line_str = line_str[6:]
                
            try:
                event_data = json.loads(line_str)
                if isinstance(event_data, dict) and "content" in event_data:
                    parts = event_data["content"].get("parts", [])
                    if parts and "text" in parts[0]:
                        reply_text += parts[0]["text"]
            except json.JSONDecodeError:
                pass
                
        if not reply_text:
            reply_text = "任务已接收并处理，未收到具体文本回复（请查看控制台日志了解详细过程）。"
            
        return {"reply": reply_text}
    except Exception as e:
        print(f"调用云端 Agent 出错: {e}")
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