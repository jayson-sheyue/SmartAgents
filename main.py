import os
import pandas as pd
from google import genai
from google.genai import types
import time
import json # 在代码最顶部添加
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
try:
    from playwright_stealth import stealth_sync # 旧版本用法
except ImportError:
    from playwright_stealth import Stealth # 2.0+ 用法
    def stealth_sync(page):
        Stealth().apply_stealth_sync(page)

load_dotenv()

# ==========================================
# 1. 平台环境配置初始化 (Setup - 使用最新 Gen AI SDK)
# ==========================================
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID（可复制 .env.example 为 .env）")

# 初始化 Gen AI Client (明确声明使用 Vertex AI 后端)
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# 测试一下大模型连通性 (可选，确保环境彻底跑通)
def test_llm_connection():
    print("正在测试与 Gemini 模型的连接...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='你好，请用一句话告诉我你准备好了。',
    )
    print(f"Gemini 回复: {response.text}\n")

# ==========================================
# 2. 封装本地技能 (Skill)
# ==========================================
# ==========================================
# 新增：长期记忆库本地封装
# ==========================================
MEMORY_FILE = "agent_memory.json"

def load_memory() -> dict:
    """内部函数：启动时加载本地记忆文件"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_user_preference(preference_key: str, preference_value: str) -> str:
    """
    【Agent 技能】当用户要求你“记住”某种偏好、规则或习惯时，调用此工具将其永久保存。
    """
    print(f"🧠 [记忆库更新] 正在将偏好写入长期记忆: {preference_key} -> {preference_value}")
    memory = load_memory()
    memory[preference_key] = preference_value
    
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)
        
    return f"已成功将偏好存入长期记忆库：{preference_key}。"

def get_default_excel_path() -> str:
    """获取默认的 Excel 文件路径"""
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(desktop_path, "Up主名称.xlsx")

def read_up_names_from_excel(file_path: str = None) -> list:
    """
    读取本地 Excel 文件获取 UP 主名单。
    如果没有找到文件，则默认返回初始值 'schmoyoho官号'。
    """
    if not file_path:
        file_path = get_default_excel_path()
    
    up_list = []
    if os.path.exists(file_path):
        print(f"✅ 成功找到 Excel 文件: {file_path}")
        try:
            # 读取 Sheet1 的第一列数据
            df = pd.read_excel(file_path, sheet_name="Sheet1")
            up_list = df.iloc[:, 0].dropna().tolist()
        except Exception as e:
            print(f"❌ 读取 Excel 出错: {e}")
    else:
        print(f"⚠️ 未在 {file_path} 找到文件，使用 SOP 默认值。")
        up_list = ["schmoyoho官号"]
        
    return up_list

def write_fans_to_excel(up_name: str, fans_count: str, file_path: str = None):
    """
    将抓取到的粉丝数回写到 Excel 中对应 UP 主的“粉丝数”列
    """
    if not file_path:
        file_path = get_default_excel_path()
        
    if not os.path.exists(file_path):
        print(f"⚠️ 找不到 Excel 文件 {file_path}，无法同步数据。")
        return
        
    try:
        df = pd.read_excel(file_path, sheet_name="Sheet1")
        
        # 确保存在“粉丝数”这一列
        if "粉丝数" not in df.columns:
            df["粉丝数"] = ""
            
        # 强制将“粉丝数”列的数据类型转换为字符串（object），防止 pandas 报错 Invalid value for dtype 'float64'
        df["粉丝数"] = df["粉丝数"].astype(str)
            
        # 第一列的列名（假设第一列就是存放 UP 主名称的地方）
        up_col_name = df.columns[0]
        
        # 找到匹配的 UP 主所在行，并更新“粉丝数”
        match_idx = df[df[up_col_name] == up_name].index
        if len(match_idx) > 0:
            df.loc[match_idx, "粉丝数"] = fans_count
            # 保存回 Excel
            df.to_excel(file_path, sheet_name="Sheet1", index=False)
            print(f"📝 成功将 {up_name} 的粉丝数 ({fans_count}) 同步到 Excel 表格！")
        else:
            print(f"⚠️ 在 Excel 中未找到 UP 主: {up_name}，无法写入粉丝数。")
            
    except Exception as e:
        print(f"❌ 写入 Excel 出错: {e}")

# ==========================================
# 3. 封装网页 RPA 技能 (Skill) - 严格对应图片 SOP
# ==========================================
def get_up_fans_data(up_name: str) -> dict:
    """
    根据 UP 主名称，自动化抓取粉丝第一页数据。
    """
    print(f"\n🚀 开始执行 RPA 任务，当前目标 UP 主: {up_name}")
    
    # 最终返回的数据结构
    result = {
        "up_name": up_name,
        "status": "", # 记录成功或"粉丝不可见"
        "fans_data": [] # 存放粉丝详情
    }

    with sync_playwright() as p:
        # 新增 args 参数：禁用 Chrome 的自动化控制提示，降低风控概率
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        state_file = "bilibili_state.json" # 用于保存登录凭证的本地文件

        # 检查是否已经有保存的登录状态
        if os.path.exists(state_file):
            print("🔑 发现本地保存的登录状态，正在尝试免密自动登录...")
            context = browser.new_context(storage_state=state_file)
            page = context.new_page()
            stealth_sync(page) # 穿上隐身衣
        else:
            browser.close()
            error_msg = "⚠️ 未找到登录状态 bilibili_state.json！如果是作为 API 运行，请先在终端执行 `python main.py login` 完成手动登录。"
            print(error_msg)
            raise Exception(error_msg)

        try:
            # === 接续原来的 SOP 步骤 1 ===
            page.goto("https://search.bilibili.com/all")
            
            # SOP 步骤 2: 填入搜索框并点击搜索
            # 注意：这里的选择器 ".search-input-el" 和 ".search-button" 是预估的，B站前端可能会变
            page.locator("input.search-input-el").fill(up_name)
            page.locator("button.search-button").click()
            
            # SOP 步骤 3: 等待3-5秒
            time.sleep(4) 
            
            # SOP 步骤 4: 点击"用户"
            page.get_by_text("用户", exact=True).click()
            time.sleep(3) # SOP 要求等待3秒
            
            # SOP 步骤 5: 点击查询结果中的第一个用户头像 (B站通常会打开新标签页)
            with context.expect_page() as new_page_info:
                # 优化定位器：寻找页面中指向 UP 主个人空间的链接
                # 为避免误点到顶部导航栏您自己的登录头像，我们增加 has_text=up_name 限制，
                # 让它点击搜索结果中包含该 UP 主名字的那个链接
                page.locator(f"a[href*='space.bilibili.com']", has_text=up_name).first.click() 
            new_page = new_page_info.value
            new_page.wait_for_load_state()

            # SOP 步骤 6: 抓取粉丝总数
            # 我们不需要点击"粉丝数"去翻列表了，直接在主页提取总数
            print("👁️ 正在尝试提取粉丝总数...")
            
            # 尝试几种可能的定位方式
            fans_count_text = ""
            
            # 方案 1: 从您截图中的侧边栏提取 div.vui_sidebar-item-right
            try:
                # 先尝试点击一下"Ta的粉丝"侧边栏，因为有时数字是动态加载的
                # 但不一定非要点击，它可能直接就在页面上
                fans_count_text = new_page.locator("div.vui_sidebar-item-right").inner_text(timeout=3000)
                if fans_count_text:
                    print(f"🎯 通过侧边栏定位器获取到粉丝数: {fans_count_text}")
            except:
                pass
                
            # 方案 2: 直接从顶部导航栏提取 (如 "粉丝数 65" 或单独的数字)
            if not fans_count_text:
                try:
                    # 匹配标题属性包含'粉丝数'的元素
                    fans_element = new_page.locator("span.nav-statistics__item-text", has_text="粉丝数")
                    if fans_element.is_visible():
                        # 获取它的下一个兄弟元素或父元素内的数字
                        fans_count_text = fans_element.locator("..").inner_text()
                        print(f"🎯 通过顶部导航定位器获取到文本: {fans_count_text}")
                except:
                    pass
            
            if fans_count_text:
                result["status"] = "成功获取"
                result["fans_data"] = {"总粉丝数": fans_count_text.replace("粉丝数", "").strip()}
                print(f"✅ 成功提取到 {up_name} 的粉丝数: {result['fans_data']['总粉丝数']}")
            else:
                result["status"] = "提取失败"
                print(f"⚠️ 无法在页面上找到粉丝数元素。")
                    
        except Exception as e:
            print(f"❌ 抓取 {up_name} 时发生错误: {str(e)}")
            result["status"] = f"抓取异常: {str(e)}"
            
        finally:
            # 无论成功与否，关闭浏览器释放资源
            browser.close()

    return result

def manual_login():
    """手动登录 B 站并保存凭证"""
    print("准备进行初次手动授权登录...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context()
        page = context.new_page()
        stealth_sync(page)
        
        page.goto("https://passport.bilibili.com/login")
        print("\n=======================================================")
        print("👉 请在弹出的浏览器窗口中，使用【扫码】或【密码】完成登录。")
        print("👉 登录成功并看到 B 站首页后，请回到这个终端界面。")
        print("=======================================================\n")
        
        input("✅ 如果您已经登录成功，请按【回车键 (Enter)】继续执行脚本...")
        
        context.storage_state(path="bilibili_state.json")
        print("💾 登录状态已成功保存至 bilibili_state.json，下次运行将自动登录！")
        browser.close()

# ==========================================
# 4. 构建 Agent 大脑 (Build & Runtime)
# ==========================================
def run_bilibili_agent(user_prompt: str):
    """
    启动 Agent，让其自主分析需求并调用相应的技能(Skills)
    """
    print("\n" + "="*50)
    print("🤖 正在唤醒 B站 RPA Agent 大脑...")
    print("="*50)
    
    # 1. 注册新技能：加上 save_user_preference
    bilibili_skills = [
        read_up_names_from_excel,
        get_up_fans_data,
        write_fans_to_excel,
        save_user_preference # <--- 新增的记忆技能
    ]
    
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    
    # === 新增逻辑：开机时读取记忆库 ===
    memory_data = load_memory()
    memory_prompt = ""
    if memory_data:
        memory_prompt = f"\n【你的长期记忆库】\n你之前记住了以下用户偏好，请在本次及以后的任务中必须严格遵守：\n{json.dumps(memory_data, ensure_ascii=False)}\n"
        print("📥 已成功加载历史长期记忆！")
    # ==================================

    # 2. 定义 Agent 的人设 (把记忆拼接进去)
    system_instruction = f"""
    你是一个强大的 B站 UP主数据分析 RPA Agent。
    你的任务是帮助用户全自动收集 B站 UP主 的粉丝数据并整理归档。
    
    你拥有以下四个核心技能 (Tools):
    1. `read_up_names_from_excel`: 获取名单。
    2. `get_up_fans_data`: 抓取数据。
    3. `write_fans_to_excel`: 保存数据。
    4. `save_user_preference`: 当用户让你“记住”特定偏好（如汇报风格、过滤规则）时，调用此工具持久化保存。
    
    【工作流指南】
    1. 分析用户指令。如果是要求你记住偏好的指令，请调用 `save_user_preference`。
    2. 如果是要求你执行抓取任务，你需要:
       a. 使用 `read_up_names_from_excel` 拿到列表
       b. 遍历列表中的每一个名字，使用 `get_up_fans_data` 抓取粉丝数
       c. 如果抓取成功，使用 `write_fans_to_excel` 将数据保存
    3. 生成最终报告。
    {memory_prompt} # <--- 动态注入的历史记忆
    """
    
    chat = client.chats.create(
        model="gemini-2.5-pro",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=bilibili_skills,
            temperature=0.2 
        )
    )
    
    print(f"👤 用户指令: {user_prompt}\n")
    response = chat.send_message(user_prompt)
    print("🤖 Agent 最终总结汇报:\n")
    print(response.text)
    print('\n任务结束！')

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        manual_login()
    else:
        # 我们不再写循环去死板调用函数了，把一切交给 Agent！
        user_command = "你好"
        
        # 启动 Agent
        run_bilibili_agent(user_command)