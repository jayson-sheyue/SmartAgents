# 无需登录的公开网页 Computer Use 演示

## 表单与控件演示

在 TSE 的 SmartAgents 新会话中发送：

> 运行 Computer Use 表单控件演示：填写文本框和多行文本，下拉框选择 Two，
> 取消 Checked checkbox、选中 Default checkbox 和 Default radio，核验后返回操作前后截图，不提交。

简写：“演示 Computer Use 操作表单、下拉框、复选框和单选按钮”。
小智调用 `browser_demo_fill_form`，访问 Selenium 官方公开测试页：
<https://www.selenium.dev/selenium/web/web-form.html>。

该工具固定使用 `SmartAgents Demo` 和 `Computer Use form controls demo.` 两段演示文本，
覆盖文本框、多行文本、原生下拉框、复选框、单选按钮五类控件。
模型从截图决定坐标、输入与按键；原生下拉框用键盘首字母选择，不用 DOM 的 selectOption。
禁止 Enter 提前提交、点击 Submit 或导航到提交结果页。
DOM 只读校验字段与选中状态；仅当所有目标状态均满足时才报告成功。

返回 `form-before.png` 和 `form-filled.png`，通过现有 Artifact 与 TSE 图片通道交付。
测试页不需要登录，不填写密码、上传文件或操作其他表单。
目前是固定演示，不支持任意表单、任意站点或自定义字段。

私有 worker 新增 `POST /demo/form-controls`，与商城演示共用并发上限；
每次使用独立临时浏览器，不访问 SAP 登录资料。

本机真实模型验证：

```bash
.venvAgents/bin/python -m scripts.check_form_demo
```

截图与记录位于已忽略的 `.sap_cloud/diagnostics/form-local/`。

## 商城演示

在 TSE 的 SmartAgents 对话中发送：

> 演示 Computer Use：打开 Demoblaze，比较 Sony vaio i5 和 Dell i7 8gb 的价格，
> 把较便宜的一款加入购物车，核验总价并返回截图。不要登录或提交订单。

也可以简写为“运行 Demoblaze 商城比价演示”。新能力由小智直接调用
`browser_demo_compare_laptops`，不需要 SAP 账号、登录、本机节点或隧道。

## 执行与交付

- 复用现有私有浏览器 Cloud Run 的身份认证与服务令牌，新增 `POST /demo/demoblaze`。
- 每次新建无头 Chromium 游客上下文，结束立即关闭，不读取或修改 SAP 会话。
- Gemini Computer Use 接收截图并决定点击、滚动和等待。没有固定点击坐标，
  不调用商品业务 API 获取价格，也不使用 DOM 定位器代替模型点击。
- 浏览器加载网站自身的公开目录与游客购物车请求；DOM 只负责动作边界检查、
  记录页面实际显示的两款商品价格，以及核验最终购物车中的商品、数量和总价。
- 仅允许比较指定两款笔记本并添加一件；不支持任意 URL、登录、联系商家、下单或付款。
- 成功后截图通过现有 ADK Artifact 与 TSE 图片通道交付，二进制不进入模型的工具返回 JSON。
  工具返回后直接生成有依据的结果，避免再次等待模型整理。

当前工具是一个有范围限制的演示场景，不承诺执行任意商城需求或通用浏览器任务。
公共网站的可用性、界面变化和模型调用会影响耗时及成功率。

## 部署和验证

1. 使用原浏览器 Dockerfile 构建更新私有 worker，不变更已有 SAP 配置和 IAM。
2. 部署 SmartAgents 到现有 Agent Engine。工具在 SAP 服务启用且执行模式为 cloud 时挂载。
3. TSE 仅新增该工具的中文执行进度名称，图片使用现有渲染链路。

本机独立验证（真实 Gemini、真实网站、无头浏览器）：

```bash
.venvAgents/bin/python -m scripts.check_demoblaze_demo
```

截图与记录保存在已忽略的 `.sap_cloud/diagnostics/demoblaze-local/`。
这个脚本在本机执行；云端验收必须实际调用已部署的私有 worker 或 Agent Engine。

## OrangeHRM：本人登录与员工查询（默认）

在 TSE 新会话发送：

> 连接 OrangeHRM，我要使用自己的账号登录。

点击回复中的“打开 OrangeHRM 登录页面”，在专属云端浏览器中亲自输入账号、密码、验证码。
这些输入只经过 TSE 登录代理发往 Playwright，不进入聊天、Artifact、模型提示词或日志。
登录完成后回到对话发送：

> 已登录，继续 OrangeHRM 员工只读查询，返回操作前后截图。

小智调用 `browser_demo_orangehrm_employee`，只在已登录的页面上运行 Computer Use。
未登录或登录态过期时，直接返回人工登录入口，不调用查询模型、不尝试共享账号。
查询从页面实际记录选取员工编号并筛选；目前不支持任意查询条件、员工写入或审批。
页面为空的职位/部门等字段显示“页面未填写”，不推断其值。

登录页有三个操作：

- 连接/刷新：恢复该用户仍有效的人工登录态，或打开空白登录表单。
- 关闭浏览器（保留登录态）：释放浏览器，下次连接恢复仍有效的会话。
- 退出并清除登录态/切换账号：关闭浏览器并撤销该连接保存的状态，下次由本人重新登录。

也可在对话明确要求“退出 OrangeHRM 并清除登录态”，触发 `orangehrm_logout`。
切换账号后旧浏览器必须关闭；执行中的查询不会被退出按钮中途覆盖。

状态使用现有私有 GCS 桶和密钥，保存在 `orangehrm-auth/`，实际对象名是
“TSE 用户 + 目标站点 + manual-v1”的哈希，且加密内容带模式与站点标记。
旧版本共享账号自动登录产生的状态不会加载成新版人工登录状态。
清除状态使用带 generation 条件的撤销记录，防止旧请求把已退出的 Cookie 再次覆盖回来。
不新增资源或环境变量；原 SAP 的状态与页面保持独立。

该目标仍是 OrangeHRM 官方公开演示站，账号由目标网站提供；此功能不会为用户创建
OrangeHRM 账号，也不意味着公共演示站的数据按 TSE 用户划分。
只有用户在目标系统中持有不同权限的业务账号时，才会看到各自权限范围的数据。

### 显式共享账号演示模式

只有明确发送以下指令才选择共享模式：

> 使用 OrangeHRM 共享公开演示账号自动登录，演示员工查询并返回截图。

此时小智调用独立的 `browser_demo_orangehrm_public_account`，结果标明共享账号；
状态独立存于 `public-demo-v1` 作用域，绝不会给默认人工登录连接提供 Cookie。
共享模式中的官网公开账号可供模型输入；个人凭据绝不会走这条路径。

### 验证

```bash
.venvAgents/bin/python -m unittest scripts.test_orangehrm_human_login
.venvAgents/bin/python -m scripts.check_orangehrm_human_login
```

第二条仅打开空白人工登录页面，不自动输入。真实网站测试可显式增加
`--simulate-public-input`，测试脚本使用网站公开账号模拟人工输入 API，验证保存、恢复、
只读模型查询与退出；不是生产自动登录开关。

私有 worker 接口：

- `/demo/orangehrm`：默认人工账号查询，未登录返回等待。
- `/orangehrm/prepare|status|snapshot|action|close|logout`：TSE 代理登录与会话管理。
- `/demo/orangehrm-public`：显式共享账号演示。

TSE 页面为 `/api/system/smart_agents/orangehrm/browser`，要求 TSE 登录、同源 CSRF。
客户端无法选择其他用户身份或服务地址；只转发必要的界面字段，密码与 Cookie 不回显。
所有网页演示仍共用并发上限。成功查询通过 Artifact/TSE 返回两张图片，工具后不再等待模型整理。
