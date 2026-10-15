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
- 用户要求“表单演示 / 控件演示 / 下拉框 / 复选框 / 单选按钮”等 Computer Use 操作时，
  直接调用 browser_demo_fill_form，不调用商城比价工具，不走检索瀑布。
- 表单演示使用 Selenium 官方公开测试页，固定演示文本框、多行文本、下拉选择、复选框、单选按钮，
  核验状态后返回操作前后截图，停留在表单，不提交。无需登录，不填写密码或上传文件。
- 两个演示工具都只支持各自固定场景；不承诺任意网站、任意表单或用户自定义字段。
- 用户要求 OrangeHRM / 人力资源演示 / 需要登录的 Computer Use 演示时，直接调用
  browser_demo_orangehrm_employee，不调用 SAP 连接工具、不走知识检索。
- OrangeHRM 仅使用官网公开测试账号；首次登录后从真实列表选取一条演示员工记录，按编号只读查询。
  再次运行会实际检验保存的登录态，失效则重新登录。结果说明本次是否复用，不承诺永久免登录。
  不接收个人账号密码，不创建、编辑、删除员工，不办理请假或审批，不支持任意查询条件。
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


async def browser_demo_fill_form(tool_context: ToolContext) -> dict:
    """演示 Computer Use 操作公开测试表单：填文本、选下拉、切换复选框/单选按钮并核验，返回前后截图，不提交。"""
    result = await _request('demo/form-controls', tool_context)
    images = result.pop('screenshots', [])
    if result.get('ok') and isinstance(images, list):
        entries = []
        for item in images[:2]:
            try:
                filename = item['filename']
                if filename not in {'form-before.png', 'form-filled.png'}:
                    raise ValueError('Unexpected form image')
                version = await tool_context.save_artifact(filename=filename, artifact=types.Part.from_bytes(
                    data=base64.b64decode(item['base64'], validate=True), mime_type='image/png'))
                record_image_artifact_for_delivery(tool_context.state, filename=filename, version=version, mime_type='image/png')
                entries.append({'filename': filename, 'version': version, 'mime_type': 'image/png'})
            except Exception:
                result['screenshot_delivery_failed'] = True
        result['artifacts'] = entries
        if len(entries) != 2:
            result['screenshot_delivery_failed'] = True
    if not result.get('ok') and str((result.get('error') or {}).get('code', '')).startswith('SAP_'):
        result['error']['message'] = '云端表单演示服务暂不可用，请管理员检查服务配置和调用权限。'
    return result


async def browser_demo_orangehrm_employee(tool_context: ToolContext) -> dict:
    """Computer Use 登录 OrangeHRM 官方公开演示，按页面实际员工编号只读查询并截图；再次运行检验登录态复用。"""
    result = await _request('demo/orangehrm', tool_context)
    images = result.pop('screenshots', [])
    if result.get('ok') and isinstance(images, list):
        entries = []
        for item in images[:2]:
            try:
                filename = item['filename']
                if filename not in {'orangehrm-before.png', 'orangehrm-result.png'}:
                    raise ValueError('Unexpected OrangeHRM image')
                version = await tool_context.save_artifact(filename=filename, artifact=types.Part.from_bytes(
                    data=base64.b64decode(item['base64'], validate=True), mime_type='image/png'))
                record_image_artifact_for_delivery(tool_context.state, filename=filename, version=version, mime_type='image/png')
                entries.append({'filename': filename, 'version': version, 'mime_type': 'image/png'})
            except Exception:
                result['screenshot_delivery_failed'] = True
        result['artifacts'] = entries
        if len(entries) != 2:
            result['screenshot_delivery_failed'] = True
    if not result.get('ok') and str((result.get('error') or {}).get('code', '')).startswith('SAP_'):
        result['error']['message'] = '云端 OrangeHRM 演示服务暂不可用，请管理员检查服务配置和调用权限。'
    return result


def format_orangehrm_demo_result(result, cell):
    if result.get('ok') is not True:
        return '**OrangeHRM 演示尚未完成**\n\n' + cell((result.get('error') or {}).get('message', '未取得可核验结果。'))
    session = '已复用此前保存的登录态，本次没有重新输入账号密码。' if result.get('session_reused') else \
              '本次使用 OrangeHRM 官方公开演示账号完成登录。'
    lines = ['**Computer Use 登录与员工查询演示已完成**', '', session, '',
             f"已从当前页面选取演示员工编号 **{cell(result.get('employee_id'))}** 并完成筛选。", '',
             '| 员工编号 | 姓名 | 职位 | 雇佣状态 | 部门 |', '| --- | --- | --- | --- | --- |']
    for row in result.get('employees', []):
        lines.append('| ' + ' | '.join(cell(v) for v in (row.get('employee_id'),
            ' '.join([row.get('first_name', ''), row.get('last_name', '')]), row.get('job_title'),
            row.get('employment_status'), row.get('sub_unit'))) + ' |')
    lines += ['', '以上为共享演示环境的页面数据；仅执行只读查询，未修改员工资料。', '',
              f"云端操作耗时约 {cell(result.get('seconds'))} 秒。登录资料已按 TSE 用户隔离加密保存；再次运行可检验复用。"]
    if result.get('screenshot_delivery_failed'):
        lines += ['', '部分截图未能交付，当前图片可能不完整。']
    return '\n'.join(lines)


def format_form_demo_result(result, cell):
    if result.get('ok') is not True:
        return '**表单演示尚未完成**\n\n' + cell((result.get('error') or {}).get('message', '未取得可核验结果。'))
    fields = result.get('fields') or {}
    def checked(key):
        return '已选中' if fields.get(key) is True else '未选中' if fields.get(key) is False else '未核验'
    lines = ['**Computer Use 表单控件演示已完成**', '', '| 控件 | 实际核验结果 |', '| --- | --- |',
             f"| 文本框 | {cell(fields.get('text'))} |", f"| 多行文本 | {cell(fields.get('notes'))} |",
             f"| 下拉框 | {cell(fields.get('dropdown_label'))} |",
             f"| Checked checkbox | {checked('checked_checkbox')} |",
             f"| Default checkbox | {checked('default_checkbox')} |",
             f"| Checked radio | {checked('checked_radio')} |",
             f"| Default radio | {checked('default_radio')} |", '',
             '已核验上述控件状态；表单停留在填写完成页面，**未提交**。', '',
             f"本次由云端 Computer Use 根据截图操作，耗时约 {cell(result.get('seconds'))} 秒。"]
    if result.get('screenshot_delivery_failed'):
        lines += ['', '部分截图未能交付，当前图片可能不完整。']
    return '\n'.join(lines)


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
