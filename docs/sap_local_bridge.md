# 云端 SmartAgents → 本机 SAP 浏览器

多人 Demo 可改用[云端浏览器](sap_cloud_browser.md)，摆脱本机节点与临时隧道。
本页仍说明 local 模式；切换到 cloud 后，不再提示用户运行这些本机脚本。

当前 PoC 保留 TSE Cloud Run 和 SmartAgents Agent Engine。新增的本机接入脚本负责：

1. 在电脑运行 SAP worker（默认 `127.0.0.1:8011`，避开旧版 8010）。
2. 建立 Cloudflare Quick Tunnel 的 HTTPS 入口。外部只能通过 Bearer 令牌调用敏感接口。
3. 将允许调用的身份绑定为 `tse:<你的TSE登录邮箱>`；其他账号收到 403，不能打开或操作浏览器。
4. 验证公开 HTTPS 服务、认证和绑定，再生成 `.sap_bridge/cloud.env`；可同步根 `.env` 的 SAP 配置。

识别发票仍在云端小智进行。采购订单号通过认证 HTTPS 发送到本机；本机 worker 调用 Gemini
Computer Use，根据截图执行三步查询，再将截图作为 Agent Artifact 返回 TSE。
SAP 密码/MFA 由人在本机专用浏览器输入，不进入对话或请求参数。

## 启动

### 推荐：独立后台节点

```bash
cd /path/to/SmartAgents
.venvAgents/bin/python -m scripts.sap_bridge_service start --tse-email name@example.com
.venvAgents/bin/python -m scripts.sap_bridge_service status
```

后台启动会同步已验证的 HTTPS 地址到部署配置，不执行云端部署。
关闭启动命令的终端或结束 Codex 对话不会主动停止节点；macOS 上节点运行期间阻止空闲系统休眠，
不阻止手动睡眠、合盖或关机。再次 `start` 会复用同一后台进程和地址。
日志保存在权限 0600 的 `.sap_bridge/service.log`，控制记录不保存令牌。

演示结束后可以显式停止：

```bash
.venvAgents/bin/python -m scripts.sap_bridge_service stop
```

该命令只停止匹配本管理器标记的进程，不会停止其他本机服务。
若已有前台启动器，请先正常停止它，再启动后台；不自动抢占现有节点。

启动成功后再运行 `bash scripts/deploy_smart_agents.sh`。部署现在会验证 HTTPS 可达性、认证和用户绑定，
失败时提前报错；部署脚本和直接 Python 部署均不启动或重启本机节点。
SAP 未登录不会阻止部署，用户仍需在专用浏览器完成登录后才能查询。

### 前台调试

本机需安装 `cloudflared` 与 Playwright Chromium，且现有 Vertex ADC/GCP 项目可用。
缺浏览器时执行 `.venvAgents/bin/python -m playwright install chromium`。
本次开发机器已有 cloudflared。安装方式见 [官方文档](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

```bash
cd /path/to/SmartAgents
.venvAgents/bin/python -m scripts.sap_local_bridge --tse-email name@example.com --sync-cloud-env
```

将 `name@example.com` 换成实际 TSE 登录邮箱。脚本会复用或生成至少 32 字符的令牌，不打印令牌，
并在 `env/local.env` 保存本机配置和邮箱绑定。云端配置写入 `.sap_bridge/cloud.env`；
`--sync-cloud-env` 仅替换根 `.env` 和已有 `smart_agents/.env` 的 SAP/识别配置，
不改其他键，不执行部署。若后者尚不存在，不创建缺少其他部署设置的残缺配置。
这些文件和登录资料已排除 Git 与 Cloud Build，配置文件权限 0600。

脚本成功会显示 `SAP_COMPUTER_USE_WORKER_URL=https://…trycloudflare.com`。
HTTPS 验证失败时不会保存新的云端地址。端口上的旧版服务不会被自动关闭；可换 `--port`。
启动脚本必须保持运行；按 Ctrl+C 关闭隧道和它启动的 worker，正常退出会保存专用浏览器登录资料。
若复用了原先已运行的新版 worker，则退出脚本只关闭隧道，保留该 worker。

## 先登录，再自行更新云端

可在第二个终端先打开与 TSE 身份相同的浏览器：

```bash
.venvAgents/bin/python -m scripts.sap_computer_use prepare --tse-email name@example.com
.venvAgents/bin/python -m scripts.sap_computer_use status --tse-email name@example.com
```

亲自在新窗口登录 SAP。既有 `adk:sap-demo` 的 Cookie 不会复制给 TSE 用户。
若登录完成，再次说「连接 SAP」会复用窗口并提示已登录，不重复要求登录。
若手动关闭专用浏览器的最后一个窗口，再次「连接 SAP」会丢弃已关闭的会话并重建浏览器，
保留同一用户的独立资料目录；若 SAP 登录已失效，仍需本人重新登录。此恢复不更换 HTTPS 隧道地址。

确认根 `.env` 已同步后，按项目原流程自行更新 SmartAgents Agent Engine；TSE 的 SAP
进度展示变更按其原流程更新 Cloud Run。本机 worker 无需部署 Cloud Run。
然后在 TSE 新会话中输入：

> 连接 SAP
>
> 查询采购订单 4500071250，返回截图。

也可上传一份有明确 PO 标签的发票/PDF，发送「识别发票并查询对应的 SAP 采购订单」。
查询与截图的范围见 [黄金路径](sap_golden_path.md)，发票范围见 [发票说明](sap_invoice_demo.md)。
检查连接用「检查 SAP 连接状态」，小智会检查本机节点与该用户浏览器状态。
用户已要求只读 SAP 查询时，不再额外征求打开窗口的确认；未登录则打开专用浏览器并提示人登录。
明确订单号的查询会自动初始化浏览器，保存的登录若已恢复则执行原查询；需要手动登录时暂停。
「有哪些订单」超出本版固定单笔查询范围，仍需补充具体采购订单号或上传发票，不会默认查示例订单。

## 连通性与生命周期

```bash
# 验证上次生成的 HTTPS 通道；不启动服务、不改配置
.venvAgents/bin/python -m scripts.sap_local_bridge --tse-email name@example.com --check-only
# 本地独立查询与截图（保存到 .sap_bridge/，不打印 base64）
.venvAgents/bin/python -m scripts.sap_computer_use query --tse-email name@example.com --order 4500071250
```

- 电脑、网络、启动脚本必须持续可用；云端不会启动你电脑的关机进程。
- Quick Tunnel 是临时测试入口，重启可能更换 hostname，停止进程后 URL 失效。
  新地址要重新同步根 `.env` 并更新 Agent Engine；不支持自动在线改配置。
  它不支持 SSE，本实现通过普通 HTTPS POST 返回结果，TSE 原有流式通道不经过此隧道。
  这些限制见 [Cloudflare 官方说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。
- 401 提示令牌不一致；403 提示邮箱未绑定；连接失败提示保持本机节点/隧道运行。
  服务端查询限时 90 秒，超时不会报告查询成功，不自动重试。
- 若新 HTTPS 地址返回 200、云端仍返回旧地址的 530，请先确认 Agent Engine 的
  `SAP_COMPUTER_USE_WORKER_URL` 已更新；只修改本地文件不改变正在运行的云端配置。
- 进程仍在运行不等于隧道可用。若本机 `/status` 正常，但临时域名公共 DNS 返回
  NXDOMAIN 或隧道就绪检查失败，需先恢复 HTTPS 入口。重建 Quick Tunnel 后地址可能变化，
  应先验证新入口，再更新 Agent Engine；不需要因入口变化部署 TSE。
- 当前为指定邮箱的一台电脑演示，不实现企业设备目录、浏览器直播或自动处理 SAP 登录。
  稳定域名的长期部署可后续替换此临时入口。

本次代码更新不会自动更新 Agent Engine 或 Cloud Run。

## TSE 中的失败恢复提示

TSE 收到 SAP 工具的连接失败（包括 HTTP 530）时，会立即在对话回答中展示固定的恢复指引，
无需等待模型整理。提示用户在运行节点的电脑上执行 `scripts.sap_bridge_service start` 和 `status`，
再回到 TSE 检查连接和重试查询。此提示不会在用户电脑自动执行脚本。

提示里的 `/path/to/SmartAgents` 是当前演示机安装路径，其他电脑需替换实际目录。
初次配置需要节点管理员提供 `--tse-email`；已有节点的 `start` 不会改变账号绑定。
只有 HTTPS 地址、令牌或云端配置变化时才提示管理员运行 `bash scripts/deploy_smart_agents.sh`；
超时、浏览器启动失败和登录失效分别显示对应排查步骤，不要求一律重新部署。
发票识别成功而 SAP 查询失败时，仍保留识别字段与失败状态，不声称已完成 SAP 查询。

启用这一界面提示需要自行更新 TSE Cloud Run；SmartAgents 的确定性 SAP 回答也包含同一指引，
更新 Agent Engine 后生效。提示不影响 SAP 之外的工具。
