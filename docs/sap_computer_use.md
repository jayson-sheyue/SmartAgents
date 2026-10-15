# SAP 采购订单查询（Computer Use）

当前已验证的是 [黄金路径](sap_golden_path.md)：按 10 位订单号查询，返回订单号与真实结果截图。
从云端 TSE 调用本机浏览器，优先使用 [本机 HTTPS 接入](sap_local_bridge.md) 的专用脚本。
供应商、币种、日期、审批状态和金额可在截图查看，未作为结构化 SAP 字段提取。
发票/PDF 前置识别见 [发票 Demo](sap_invoice_demo.md)。旧探索模式仍保留，尚未通过真实端到端验证。
Gemini Computer Use 根据截图决定动作，
Playwright 只执行坐标点击、键盘、滚动；不会通过 SAP API、DOM 抽取业务字段。
DOM 只用于登录检测、按钮防护、输入框判断与订单身份核验。

## 启动与登录

执行服务在带桌面的本机运行，SmartAgent 可通过认证 HTTP 调用。默认关闭，不部署任何云服务。
使用项目现有虚拟环境；如尚无浏览器，执行 `.venvAgents/bin/python -m playwright install chromium`。

在 `env/local.env`（已忽略）加入：

```dotenv
SAP_COMPUTER_USE_ENABLED=true
SAP_COMPUTER_USE_WORKER_URL=http://127.0.0.1:8010
SAP_COMPUTER_USE_TOKEN=<至少32字符随机令牌>
SAP_BROWSER_URL=https://your-tenant.s4hana.cloud.sap/ui?sap-language=en#Shell-home
SAP_COMPUTER_USE_MODEL=gemini-3.8-flash
```

令牌用 `.venvAgents/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成，
只放在本地环境文件。模型通过现有 Vertex ADC/GCP_PROJECT_ID/代理设置访问 Google。
worker 需要 google-genai>=2.7.0；依赖见 `services/sap_computer_use/requirements.txt`。

```bash
# 终端1：保持运行，不要多 worker/process，浏览器状态在进程内
.venvAgents/bin/python -m services.sap_computer_use.server
# 终端2：打开独立浏览器
.venvAgents/bin/python -m scripts.sap_computer_use prepare --user-id sap-demo
```

在新打开的浏览器窗口亲自登录 SAP（SSO/验证码/MFA 也由人完成），进入 SAP 业务首页。
已有 Chrome 的登录态不会被复制。然后运行：

```bash
.venvAgents/bin/python -m scripts.sap_computer_use query --user-id sap-demo --order 4500071250
.venvAgents/bin/python -m scripts.sap_computer_use close --user-id sap-demo
```

CLI 与 ADK 聊天是不同入口，务必保持相同 user_id；CLI 默认 sap-demo。
使用聊天时先说「连接 SAP」，在该工具打开的浏览器登录，再说：
「查询 SAP 采购订单 4500071250，汇总供应商、金额、日期和审批状态」。
聊天工具自动用可信 ToolContext 用户身份绑定浏览器，模型不能指定或切换别人的 user_id。
TSE 会话优先使用现有 `tse_user_email` + `tse_auth_source=tse_app`，因此无需更改 TSE 业务接口。
如果 ADK 停在另一个专家，先返回调度助手小智。

## 执行范围与失败处理

- 每个用户独立持久化 browser profile，目录权限 0700，最多 4 个活跃浏览器；同用户查询串行。
  查询前及正常关闭时另存权限 0600 的登录状态文件，以恢复临时会话 Cookie；
  该目录已排除 Git 和 Cloud Build 上传。SAP 服务端使会话失效时仍需重新登录。
- 业务请求只允许同一个 SAP 租户 HTTPS；静态资源额外允许 `ui5.sap.com` 与
  `sapui5.hana.ondemand.com` 的 GET（XHR 仅限 `/resources/`）。不放行外站导航或任意 XHR。
  拦截 POST/PATCH/PUT/DELETE 等写请求；
  唯一 POST 例外是 SAP UI5 的 `$batch`，MIME 中每个子请求必须是 GET，无 changeset/请求体。
  这是检查 UI 发出的网络请求，不是调用 SAP API 获取数据。
- Edit/Create/Copy/Delete/Save/Approve/Post 等按钮与密码输入由执行层拦截。
  查询输入只允许本次订单号。未知动作拒绝；未核验详情页订单号不会报告成功。
- 单次最多 24 轮、180 秒。只记录动作名和步数，不记录凭据、截图或响应正文。
  拦截请求仅记录方法和服务路径前缀，不记录查询参数或请求体。
  模型上下文会包含订单页面截图；结果中的空字段代表未读到，行项目不承诺完整。
  使用低思考配置，历史调用 ID/签名保留，仅上传最新截图；模型优先导航到已限定的订单查询页。
  认证后的 `/snapshot` 仅提供当前用户独立浏览器截图，可用于本地排查；截图不由服务落盘。
- 登录过期、MFA、模型 `require_confirmation` 都停止，提示人检查/操作后重新发起。
  不自动确认，也不自动处理验证码。浏览器查询取消或超时不自动重试。
- 单靠按钮名无法识别所有业务动作，因此真实使用仍应配置 SAP **只读角色**。
  某些 UI 个性化/日志 POST 也会被保守拦截；非 OData 请求的拦截不会中止查询。
  实测 SAP 的 `sap-fesr-only` 性能上报属于这类。不能为此关闭写入防护。

## TSE / Agent Engine 云端接入

线上尚未部署。Cloud Run/Agent Engine 不能访问你本机的 127.0.0.1 或自动继承本机 Chrome 会话。
后续云端验证需要给这个独立 worker 配置受保护的 HTTPS 可达入口，并配置相同令牌。
用户需在 worker 所在机器的独立浏览器亲自登录；本阶段尚无远程登录/浏览器直播界面。
不要公开裸服务端口，不要把令牌写进前端 JS。工具结果仍是普通 ADK function_response，兼容现有 TSE 流式协议。
本阶段不改变 TSE 其他功能、不触发部署；仅在你批准后规划在线 worker 和登录体验。

官方机制参考：[Gemini Computer Use](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/computer-use)。
