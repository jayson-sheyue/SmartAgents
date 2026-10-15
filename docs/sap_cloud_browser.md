# SAP 云端浏览器 Demo

此版本让 TSE 和 Agent Engine 共用一个独立的 Cloud Run 浏览器服务，不依赖开发者电脑或临时 HTTPS 隧道。
代码已提供，创建云端资源、更新 Agent Engine 与 TSE 必须由管理员显式执行。

## 用户体验

1. 登录 TSE，在 SmartAgents 对话发送“连接 SAP”。
2. 点击“打开 SAP 云端登录页面”。链接在新标签页打开，不离开原对话。
3. 在画面上点击输入框，用下方输入栏发送用户名、密码或验证码；支持 Tab、Enter 等按键。
4. 页面显示“已登录”后，回到原对话发送“已登录，继续查询”，或上传演示发票查询订单。
5. 结果截图仍通过原聊天返回。密码、验证码和人工登录操作不发送给 Gemini，也不写入聊天历史。

每个 TSE 登录邮箱拥有独立 Browser Context，不能从前端指定别人的会话。
首次使用需要在云端浏览器重新登录：不会上传或复制原本机 Chrome 的登录资料。
已有登录仍有效时可复用；SAP 过期、SSO、MFA 和验证码需要本人处理。

## 云端资源与权限

默认服务 `sap-browser-demo`，区域 `us-central1`，2 CPU、4 GiB，最少 0 个、最多 1 个实例，
实例 CPU 持续分配，默认最多 4 个活跃浏览器会话。空闲 15 分钟的会话在后续连接请求时回收。
这适合几个用户的 PoC；无请求时允许自动缩至 0，下次请求会冷启动。
保留实例期间仍按实例计费，缩至 0 后停止该实例的计算计费；不会在最后一次请求后立即关闭。
缩容会丢失正在进行的窗口，已加密保存且仍有效的登录状态可在重新连接时恢复。
登录页面持续轮询会产生请求，结束使用后应关闭该页面。这不是千人并发执行器。

- Cloud Run 私有入口：仅配置的 TSE 与 Agent Engine 服务账号具有 `roles/run.invoker`。
- 同时校验应用 Bearer 令牌，令牌不发送给用户浏览器。
- Worker 使用专用服务账号：项目级 `roles/aiplatform.user` 调用 Gemini；专用桶级
  `roles/storage.objectUser`；两个 Secret 的 `roles/secretmanager.secretAccessor`。
- 私有 GCS 桶只保存按用户哈希命名的 **Fernet 加密登录状态**（Cookies 与浏览器存储），
  不保存密码输入字段或截图。加密密钥放在 Secret Manager，重新部署不更换此密钥。
  登录态本身仍是敏感凭据，桶不能公开，不能放入 TSE 附件桶。
- GCS generation 条件写入防止旧服务版本覆盖新会话资料。服务重启会丢失正在进行的窗口，
  已完成并保存的登录态可以恢复；未完成登录时需重新连接。不能依靠 Cloud Run 会话亲和性保证窗口存活。

Cloud Run 会话亲和性只是尽力而为，详情见
[官方说明](https://docs.cloud.google.com/run/docs/configuring/session-affinity)。

## 部署前配置

推荐使用统一管理入口（显式运行才会创建或更新云端资源）：

```bash
cd /path/to/SmartAgents
.venvAgents/bin/python -m scripts.deploy_sap_stack
```

统一入口从根 `.env` 读取项目与引擎，从实际线上服务发现 TSE 和 Agent Engine
的运行身份，按需创建专用浏览器服务账号、私有桶与 Secret，然后依次部署浏览器、
Agent Engine、TSE。原本机配置中有唯一 TSE 绑定邮箱和 SAP URL 时可以沿用；
否则需提供 `SAP_DEPLOY_CHECK_USER` 和 `SAP_BROWSER_URL`。不会复制本机浏览器登录态。

日常更新只部署变动组件：

```bash
.venvAgents/bin/python -m scripts.deploy_sap_stack --component agent
.venvAgents/bin/python -m scripts.deploy_sap_stack --component browser
.venvAgents/bin/python -m scripts.deploy_sap_stack --component tse
```

TSE 先部署无正式流量的 `sap-cloud` 版本，通过基础 HTTP 检查后才切换正式流量。
`SAP_TSE_SERVICE`、`SAP_TSE_REGION` 和 `--tse-path` 可覆盖现有 TSE 的部署位置。
TSE 所有其他环境变量、运行身份与服务设置通过增量更新保留。
SmartAgents 中的 `sap_transport.py` 与 `sap_recovery.py` 是共享协议辅助代码的来源，
部署 TSE 时自动同步；TSE API 集中在 `smart_agents_routes.py`，路径与 NDJSON 协议不变。

TSE GitHub Actions 已添加 SAP 服务地址发现与 Secret Manager 引用；无需新增 GitHub
令牌 Secret。该工作流仍保留原有 preview 发布方式，不自动切换正式流量。

以下是手工指定配置的方式，适用于覆盖自动发现结果或逐个运行底层部署脚本。

在 SmartAgents 根 `.env` 填写下列管理配置（不要发到聊天中）：

```ini
GCP_PROJECT_ID=your-project
SAP_CLOUD_REGION=us-central1
SAP_CLOUD_SERVICE=sap-browser-demo
SAP_CLOUD_SERVICE_ACCOUNT=sap-browser-worker@your-project.iam.gserviceaccount.com
SAP_AUTH_STATE_BUCKET=your-project-private-sap-auth
SAP_CLOUD_INVOKER_ACCOUNTS=tse-runtime@your-project.iam.gserviceaccount.com,agent-runtime@your-project.iam.gserviceaccount.com
SAP_DEPLOY_CHECK_USER=tse:your-tse-login@example.com
SAP_BROWSER_URL=https://your-tenant.s4hana.cloud.sap/ui#PurchaseOrder-manage
SAP_LOGIN_ALLOWED_ORIGINS=https://your-exact-sap-login-provider.example.com
# 若 SAP Trial 必须从 Trial Center 进入，可配置该获准站点的完整入口链接
# SAP_LOGIN_START_URL=https://your-approved-trial-portal.example.com/start
SAP_CLOUD_MAX_SESSIONS=4
```

必须先创建或选择专用 worker 服务账号。调用账号填写 **实际运行身份**，不是你登录 gcloud 的个人邮箱。
TSE 的账号可从 Cloud Run 服务的 service identity 查到；Agent Engine 若未指定自定义账号，
通常是 `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com`，以引擎实际配置为准。
SDK 运行时需要能获取面向目标 Cloud Run URL 的 OIDC ID token。

`SAP_LOGIN_ALLOWED_ORIGINS` 必须填写精确 HTTPS origin，可用逗号分隔。SAP 租户自身 origin 自动允许。
跳转到未配置的 SSO 域名时，登录页会报告该 origin，不显示或操作其画面；由管理员确认后更新配置。
不能填写 `*`、带密码的 URL 或任意网站。若 SAP 在云端限制登录，需要先验证目标站点支持云端浏览器。
若 Trial Center/SSO 是必经入口，可配置 `SAP_LOGIN_START_URL`，其 origin 必须同时列入允许名单；
不要使用一次性登录票据作为长期配置。登录过程中打开的业务标签页会在当前用户的上下文中被接管。

管理员需有 Cloud Build、Cloud Run 部署、服务账号使用、相关 IAM、Secret 和桶管理权限。
部署脚本会启用所需 API、创建私有桶和 Secret、构建容器并授权上述身份。
它不会创建服务账号、不会修改 TSE 或 Agent Engine 线上版本。

## 部署顺序

```bash
cd /path/to/SmartAgents
bash scripts/deploy_sap_browser_cloudrun.sh
# Worker 就绪后，脚本同步根 .env，并写 .sap_cloud/cloud.env（权限 0600）
bash scripts/deploy_smart_agents.sh
```

`.sap_cloud/cloud.env` 含令牌，已排除 Git 与 Cloud Build。不要将它上传给客户。
Agent Engine 部署检查在 cloud 模式下验证云端 worker，不再检查本机隧道。
本地部署预检查可能需要 gcloud 登录用户有该服务的调用权限；线上调用身份由上面的 invoker 配置决定。

然后更新 TSE Cloud Run 的代码，并设置：

```ini
SAP_BROWSER_EXECUTION_MODE=cloud
SAP_COMPUTER_USE_WORKER_URL=https://actual-sap-browser-service.run.app
SAP_COMPUTER_USE_IAM_AUTH=true
```

TSE 的 `SAP_COMPUTER_USE_TOKEN` 使用与 worker 一致的 Secret Manager Secret 注入；
需要给 TSE 运行账号该 token Secret 的读取权限，不能给它登录状态加密密钥。
例如管理员执行：

```bash
gcloud secrets add-iam-policy-binding sap-browser-token \
  --project=YOUR_PROJECT --member=serviceAccount:YOUR_TSE_RUNTIME_SA \
  --role=roles/secretmanager.secretAccessor
gcloud run services update YOUR_TSE_SERVICE --project=YOUR_PROJECT --region=YOUR_TSE_REGION \
  --update-env-vars=SAP_BROWSER_EXECUTION_MODE=cloud,SAP_COMPUTER_USE_WORKER_URL=YOUR_WORKER_URL,SAP_COMPUTER_USE_IAM_AUTH=true \
  --update-secrets=SAP_COMPUTER_USE_TOKEN=sap-browser-token:latest
```

这只修改 SAP 对接参数；TSE 新代码仍需按原项目流程构建部署。
Worker 使用稳定的服务 URL，重新部署通常不改变地址；旧本机启动器不用再运行。
不要在迁移完成前停止仍被旧线上版本使用的本机服务。云端启用后，可自行停止旧节点。

## 验收与边界

- 至少两个 TSE 账号分别打开云端登录页，确认用户 A 登录后用户 B 仍未登录。
- 关闭自己的会话、重新连接，确认有效登录态可恢复。
- 查询指定采购订单，确认显示云端执行并返回真实截图。
- 重启 worker 后重新连接；已经保存的认证可恢复，未完成登录需要重做。
- 连接失败时 TSE 提示云端服务与 IAM 排查，不提示用户启动本机脚本。

登录页是截图与人工动作代理，不是完整远程桌面；只提供点击、输入、有限按键及滚动。
登录完成后关闭人工操作通道，查询仍只读，不新增创建、编辑或过账能力。
本次自动测试使用真实无头 Chromium 与模拟 SAP 页面、模拟模型，不证明实际云端 SAP 登录或 Gemini 调用已经通过。
云端容器构建、IAM、SAP 的实际 SSO 与查询须部署后验证。
扩展到多实例或大规模用户需要会话路由、分布式协调和任务队列，不能直接调高 max-instances。
