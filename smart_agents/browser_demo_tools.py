"""Public guest browser demo, using the existing private browser transport."""
import base64

from google.adk.tools import ToolContext
from google.genai import types

from smart_agents.sap_tools import _request
from smart_agents.artifact_callbacks import record_image_artifact_for_delivery

BROWSER_DEMO_INSTRUCTION = '''
【公开网页 Computer Use 演示】
- 用户要求 Demoblaze / 模拟商城 / 笔记本比价加购物车 / 无需登录的网页操作演示时，
  由小智直接调用 browser_demo_compare_laptops，不转子 Agent，不走知识检索瀑布，不连接 SAP。
- 本工具是固定小场景：云端独立游客浏览器，查看 Sony vaio i5 和 Dell i7 8gb 的价格，
  比较后将较便宜的一款加入购物车并核验总价，返回截图。不需要登录或本机服务。
- 仅支持这个场景，不声称可以操作任意网站，不接受购买、付款或登录任务。
- 失败如实说明，不自动重复运行；仅根据工具结果说明价格、商品和执行结果。
'''


async def browser_demo_compare_laptops(tool_context: ToolContext) -> dict:
    """演示 Computer Use：在 Demoblaze 游客商城比较两款笔记本、加购物车并截图，不登录或下单。"""
    result = await _request('demo/demoblaze', tool_context)
    encoded = result.pop('screenshot_base64', None)
    if result.get('ok') and encoded:
        filename = 'demoblaze-cart.png'
        try:
            version = await tool_context.save_artifact(filename=filename, artifact=types.Part.from_bytes(
                data=base64.b64decode(encoded, validate=True), mime_type='image/png'))
            record_image_artifact_for_delivery(tool_context.state, filename=filename, version=version, mime_type='image/png')
            result['artifacts'] = [{'filename': filename, 'version': version, 'mime_type': 'image/png'}]
        except Exception:
            result['screenshot_delivery_failed'] = True
    if not result.get('ok') and str((result.get('error') or {}).get('code', '')).startswith('SAP_'):
        result['error']['message'] = '云端浏览器演示服务暂不可用，请管理员检查服务配置和调用权限。'
    return result


def format_browser_demo_result(result, cell):
    if result.get('ok') is not True:
        return '**网页演示尚未完成**\n\n' + cell((result.get('error') or {}).get('message', '未取得可核验结果。'))
    lines = ['**Computer Use 商城演示已完成**', '',
             '| 实际查看的商品 | 页面价格（USD） |', '| --- | ---: |']
    for item in result.get('products', []):
        lines.append('| ' + cell(item.get('name')) + ' | ' + cell(item.get('price')) + ' |')
    cart = result.get('cart') or {}
    lines += ['', f"已将 **{cell(cart.get('name'))}** 加入游客购物车，数量 **{cell(cart.get('quantity'))}**，"
              f"核验购物车总价 **USD {cell(cart.get('total'))}**。", '',
              f"本次由云端 Computer Use 根据截图操作，耗时约 {cell(result.get('seconds'))} 秒。未登录、未提交订单。"]
    return '\n'.join(lines)
