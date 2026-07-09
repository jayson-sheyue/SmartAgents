import asyncio
import json
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    # 配置如何以子进程启动我们的 MCP Server
    # 注意：这里我们使用虚拟环境的 Python，以确保它能找到 Playwright 等依赖
    server_params = StdioServerParameters(
        command="/Users/apple/Desktop/Demo/SmartAgents/.venvAgents/bin/python",
        args=["mcp_server/bilibili_mcp.py"]
    )

    print("🔌 正在启动并连接到本地 MCP Server...")
    # 使用 stdio 管道连接到 Server 进程
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. 握手初始化连接
            await session.initialize()
            print("✅ MCP Server 连接并初始化成功！\n")

            # 2. 查询 Server 暴露了哪些 Tools
            tools_response = await session.list_tools()
            print("🛠️  Server 暴露的可用工具列表:")
            for tool in tools_response.tools:
                print(f"  - {tool.name}: {tool.description}")
            print("-" * 40)

            # 3. 模拟大模型调用: 执行 fetch_fans_data 工具
            print("\n🤖 模拟 Agent 调用工具 -> [fetch_fans_data]")
            result = await session.call_tool("fetch_fans_data", arguments={"up_name": "示例UP主"})
            
            # 解析并打印结果 (MCP 协议返回的是结构化的 Content 对象)
            # 为了方便看，我们将其内容格式化输出
            response_text = result.content[0].text
            print(f"📦 工具返回结果:\n{response_text}")

            print("\n🎉 本地测试完毕！")

if __name__ == "__main__":
    asyncio.run(main())
