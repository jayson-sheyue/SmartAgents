import requests
from google.adk.agents.llm_agent import Agent
from google.adk.models import Gemini
from google.genai import Client
from functools import cached_property
import os

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

# ==========================================
# 0. 配置企业级 Vertex AI 认证 (替代 API KEY)
# ==========================================
PROJECT_ID = "webeye-internal-test"
LOCATION = "us-central1"

print("🔐 正在初始化基于 Vertex AI 的底层 Client...")

# ADK 2.0 中自定义底层 Client 的官方推荐方式是继承 Gemini 并重写 api_client
class VertexGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        # 在这里配置 Vertex AI 参数，它会自动使用 gcloud auth 凭证
        return Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

vertex_model = VertexGemini(model='gemini-2.5-pro')

# ==========================================
# 1. 配置您的本地节点地址 (通过 ngrok 穿透的 URL)
# ==========================================
# 我们现在从环境变量读取 NGROK_URL，避免硬编码
from dotenv import load_dotenv
load_dotenv()

NGROK_URL = os.getenv("NGROK_URL", "https://quaking-resume-module.ngrok-free.dev")
if NGROK_URL == "https://quaking-resume-module.ngrok-free.dev":
    print("⚠️ 警告: 目前使用的是默认的 Ngrok URL，请在 .env 文件中配置您最新的 NGROK_URL！")

# ==========================================
# 2. 将 RESTful API 包装成云端大脑的 Tool (技能)
# ==========================================
def get_up_list_from_node() -> list:
    """调用本地节点：获取桌面 Excel 中的 UP 主名单"""
    print("🌐 [云端请求] 正在调用本地 API 获取名单...")
    try:
        response = requests.get(f"{NGROK_URL}/api/get_up_list", timeout=10)
        return response.json().get("data", [])
    except Exception as e:
        print(f"❌ 请求本地节点失败: {e}")
        return []

def fetch_fans_data_from_node(up_name: str) -> dict:
    """调用本地节点：启动本地浏览器抓取指定 UP 主的粉丝数"""
    print(f"🌐 [云端请求] 正在命令本地浏览器抓取: {up_name}")
    try:
        response = requests.post(f"{NGROK_URL}/api/fetch_fans_data", json={"up_name": up_name}, timeout=120)
        return response.json().get("data", {})
    except Exception as e:
        print(f"❌ 请求本地节点失败: {e}")
        return {"status": f"请求本地节点失败: {e}"}

def write_excel_to_node(up_name: str, fans_count: str) -> str:
    """调用本地节点：将粉丝数回写到桌面 Excel"""
    print(f"🌐 [云端请求] 正在命令本地写入 Excel: {up_name} -> {fans_count}")
    try:
        response = requests.post(f"{NGROK_URL}/api/write_excel", json={"up_name": up_name, "fans_count": fans_count}, timeout=10)
        return response.json().get("message", "")
    except Exception as e:
        print(f"❌ 请求本地节点失败: {e}")
        return f"请求本地节点失败: {e}"

# ==========================================
# 3. 使用 ADK 构建云端 Agent (Build & Runtime)
# ==========================================
# 定义一个异步回调函数，每次大模型回复结束后，自动将本次会话抛给 Memory Bank 提取关键记忆
async def generate_memories_callback(callback_context: CallbackContext):
    # 将整个 session 对话历史存入云端记忆库
    await callback_context.add_session_to_memory()
    return None

# 将刚才写好的网络请求函数，以及官方的 Memory 提取工具赋予给 Agent
adk_tools = [get_up_list_from_node, fetch_fans_data_from_node, write_excel_to_node, PreloadMemoryTool()]

system_instruction = f"""
你是一个强大的 B站 UP主数据分析 RPA Agent。
你现在运行在云端，但你拥有三个通过网络连接到本地节点的技能(Tools)。
此外，你可以通过原生 Memory Bank 自动访问用户的历史偏好（在每轮对话开始前已被自动加载）。

【工作流指南】
1. 分析用户指令，留意当前上下文中加载的记忆偏好，并在任务中严格遵守。
2. 如果用户下达了执行任务、抓取数据等指令，你需要：
   - 首先，调用 `get_up_list_from_node` 获取完整的 UP主 列表。
   - 针对每一个 UP主，依次调用 `fetch_fans_data_from_node` 获取粉丝数。
   - 成功获取后，调用 `write_excel_to_node` 将其保存。
3. 在处理完所有名单后，给用户生成一份简短的任务完成报告。
"""

print("☁️ 正在云端初始化 ADK Agent 大脑...")
# 注意：在 ADK 2.0 中，如果在命令行使用 adk run 运行，
# 它默认会去寻找当前目录下 agent.py 文件中的 root_agent 变量。
# 为了保持兼容性，我们将 cloud_agent 同时也赋值给 root_agent

# 我们显式创建 Gemini 模型实例，并配置 Vertex AI 参数
# (这部分代码已经移到文件顶部)

root_agent = Agent(
    name="Bilibili_Cloud_ADK_Agent",
    model=vertex_model,  # 使用自定义认证的模型实例
    description="负责统筹规划和通过 REST API 调用远程节点完成 B 站数据抓取的云端智能体",
    instruction=system_instruction,
    tools=adk_tools,
    after_agent_callback=generate_memories_callback
)

cloud_agent = root_agent

# ==========================================
# 4. 创建发布用的部署脚本 (Deployment)
# ==========================================
if __name__ == "__main__":
    import sys
    # 如果通过 python3 cloud_agent.py 运行，且参数是 deploy，则执行部署
    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        print("🚀 准备部署到 Agent Platform...")
        from google.cloud.aiplatform import init
        # 使用命令行工具 adk deploy 部署
        print("💡 若要部署到云端，请使用: adk deploy")
    else:
        print("💡 若要本地交互运行，请使用: adk run cloud_agent")
        print("💡 若要部署到云端，请运行: python3 cloud_agent.py deploy")
