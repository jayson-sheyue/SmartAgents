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

## OrangeHRM：登录与员工查询

在 TSE 新会话发送：

> 运行 OrangeHRM Computer Use 演示：使用网站公开演示账号登录，
> 从当前员工列表选取一条记录，按员工编号只读筛选查询，返回结果和操作前后截图。

然后再发送：

> 再运行一次 OrangeHRM 员工查询，验证是否复用了登录态，并返回截图。

小智直接调用 `browser_demo_orangehrm_employee`，不连接 SAP、不需要本机服务。
浏览器访问官方公开 Demo：<https://opensource-demo.orangehrmlive.com/>。
使用登录页公开展示的 `Admin / admin123` 测试账号，不接受个人凭据。
所有填写与点击坐标来自 Gemini Computer Use；DOM 仅用于操作边界、选取页面实际存在的
演示员工编号与核验筛选后的实际结果，浏览器自身请求员工接口，程序不直接调用业务接口查询。
共享演示数据会变化，员工编号从当次页面选取，不能指定任意员工或固定业务数据。

每次创建新浏览器，先访问受保护的员工列表页检验已有 Cookie；仍需登录时才重新登录。
登录资料使用原私有 GCS 桶、原加密密钥，存于独立的 `orangehrm-auth/<用户哈希>.enc`，
与 `sap-auth/` 分离；按可信 TSE 身份隔离，保存时使用 GCS generation 条件防止覆盖。
仅存该 Demo 域名的 Cookie/localStorage，不保存密码、截图或其他站点资料。
这可在浏览器关闭、Cloud Run 缩减至零后恢复仍有效的站点会话；站点会话过期仍会重新登录。
公开测试账号是共享账号，因此隔离浏览器资料不代表各用户拥有独立的 OrangeHRM 后端数据。

仅允许登录表单 POST 与只读员工查询 GET；禁止新增、编辑、删除、审批等业务请求。
成功返回 `orangehrm-before.png` 与 `orangehrm-result.png`，沿用 Artifact/TSE 图片通道，
图片 Base64 从工具 JSON 移除，不再等待第二次模型整理。

本机真实验证（先登录查询，再关闭浏览器并用保存的状态创建第二个浏览器验证）：

```bash
.venvAgents/bin/python -m scripts.check_orangehrm_demo
```

本机验证仅临时保存在内存；生产使用加密 GCS。私有 worker 新增
`POST /demo/orangehrm`，与其他网页演示共享并发限制。无需新增服务、密钥或环境变量。
