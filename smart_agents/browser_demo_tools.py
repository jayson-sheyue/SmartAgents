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
- OrangeHRM 默认人工登录：无登录态时必须返回专属云端登录页面链接，等待用户本人完成登录；
  用户说“已登录，继续 OrangeHRM 查询”时再次调用 browser_demo_orangehrm_employee。
  不向用户索取密码/验证码，不接收聊天中的凭据，不从公共页面获取凭据代替本人登录，不自动切换共享账号。
- 用户要求连接/登录 OrangeHRM 时调用 orangehrm_prepare_browser；要求退出/清除 OrangeHRM 登录态或切换账号时
  调用 orangehrm_logout。关闭页面或新建聊天不等于退出；退出后必须重新人工登录。
- 仅当用户明确要求“使用共享公开演示账号自动登录”时，才调用 browser_demo_orangehrm_public_account；
  此模式必须标注共享账号，独立保存登录态，不得把它当成用户自己的账号或默认模式。
- 员工查询仅按页面实际记录做只读演示，不创建、编辑、删除员工，不办理请假或审批，不支持任意查询条件。
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
    """用当前用户亲自登录的 OrangeHRM 会话查询员工并截图；未登录返回人工登录链接，绝不自动输入账号密码。"""
    return await _orangehrm_query('demo/orangehrm', tool_context)


async def browser_demo_orangehrm_public_account(tool_context: ToolContext) -> dict:
    """仅在用户明确要求共享公开账号自动登录演示时使用；此模式与人工登录账号隔离。"""
    return await _orangehrm_query('demo/orangehrm-public', tool_context)


async def orangehrm_prepare_browser(tool_context: ToolContext) -> dict:
    """打开当前 TSE 用户的 OrangeHRM 人工登录入口；不索取密码或验证码。"""
    return await _request('orangehrm/prepare', tool_context)


async def orangehrm_logout(tool_context: ToolContext) -> dict:
    """按用户明确退出/清除登录态/切换账号指令，关闭其 OrangeHRM 浏览器并清除人工登录态。"""
    return await _request('orangehrm/logout', tool_context)


async def _orangehrm_query(action, tool_context):
    result = await _request(action, tool_context)
    images = result.pop('screenshots', [])
    if result.get('ok') and not result.get('wait_user') and result.get('employee_id') and isinstance(images, list):
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
    link = '[打开 OrangeHRM 登录页面](/api/system/smart_agents/orangehrm/browser)'
    if result.get('wait_user') and result.get('logged_in') is False:
        return ('**请先由本人登录 OrangeHRM**\n\n' + link +
                '，在该页面输入账号、密码及验证码。完成后回到此对话发送“已登录，继续 OrangeHRM 查询”。'
                '\n\n登录输入直接发送到你的专属浏览器，不进入 Agent 对话或查询模型；当前尚未执行员工查询。')
    if result.get('ok') is not True:
        return '**OrangeHRM 操作尚未完成**\n\n' + cell((result.get('error') or {}).get('message', '未取得可核验结果。'))
    if result.get('status') == 'logged_out':
        return '**已清除 OrangeHRM 登录态**\n\n浏览器已关闭。再次连接需亲自登录：' + link
    if not result.get('employee_id'):
        return '**OrangeHRM 已登录**\n\n请回到对话继续查询。管理连接：' + link
    shared = result.get('auth_mode') == 'public_demo'
    session = ('本次是**共享公开账号自动登录演示**，不是你的个人业务账号。' if shared else
               '本次使用**你亲自登录并保存的会话**完成查询；查询模型未接收账号密码。')
    lines = ['**Computer Use 员工查询演示已完成**', '', session, '',
             f"已从当前页面选取演示员工编号 **{cell(result.get('employee_id'))}** 并完成筛选。", '',
             '| 员工编号 | 姓名 | 职位 | 雇佣状态 | 部门 |', '| --- | --- | --- | --- | --- |']
    for row in result.get('employees', []):
        lines.append('| ' + ' | '.join(cell(v or '页面未填写') for v in (row.get('employee_id'),
            ' '.join([row.get('first_name', ''), row.get('last_name', '')]), row.get('job_title'),
            row.get('employment_status'), row.get('sub_unit'))) + ' |')
    lines += ['', '以上为演示站点的页面数据；仅执行只读查询，未修改员工资料。', '',
              f"云端操作耗时约 {cell(result.get('seconds'))} 秒。"]
    if not shared:
        lines += ['', '登录态按 TSE 用户和目标站点隔离加密保存。切换账号或清除登录态：' + link]
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
