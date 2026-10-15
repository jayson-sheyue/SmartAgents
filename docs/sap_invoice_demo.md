# 发票图片/PDF → SAP Computer Use

能力挂在小智（SmartAgents_Dispatcher），随 `SAP_COMPUTER_USE_ENABLED=true` 启用。
云端调用本机浏览器的启动与配置流程见 [本机 HTTPS 接入](sap_local_bridge.md)。
Gemini 原生读取当前上传的 PDF/PNG/JPEG/WebP，提取发票号、采购订单号、供应商、
总金额、币种与日期，并返回字段证据原文。无需另建 OCR 服务或安装 PDF 渲染依赖。

## TSE 对话触发

在 SmartAgents 对话上传一份发票，发送：

> 识别这份发票，查询其中采购订单在 SAP 的记录，并返回查询截图。

- `sap_query_from_invoice`：识别 → 唯一且明确标注的 10 位 PO → SAP 只读查询 → 截图 Artifact。
- `invoice_extract`：只识别，不查询；例如「提取这份发票的供应商、金额和订单号」。
- `sap_query_recognized_invoice`：SAP 尚未登录时保留本会话识别结果；用户亲自登录后续查。
- 多份附件需选择序号（工具序号从 0 开始）。缺失/多个 PO 时请用户补充或选择，
  然后调用 `sap_query_purchase_order` 查询用户明确给出的订单号。

不把发票号、税号猜成订单号；不按演示默认订单补齐。识别内容带证据，但仍可能有 OCR 误读，
客户演示前核对样本。供应商与金额来自发票，SAP 黄金路径结果来自截图；
本版没有自动核对税、运费、金额口径，不宣称完成账务匹配，不新建/编辑/过账。

## 本地脚本

复用现有 Vertex ADC、项目/模型位置和代理配置。单份 inline 附件限 20 MB，识别调用超时 45 秒。

```bash
# 仅识别
.venvAgents/bin/python -m scripts.sap_invoice_demo --file /path/invoice.pdf
# 识别后调用已运行的 SAP worker；--user 要与该用户的 SAP 登录会话相同
.venvAgents/bin/python -m scripts.sap_invoice_demo --file /path/invoice.png --query-sap --user sap-demo
```

默认截图保存到 `/private/tmp/sap-invoice-demo/`。脚本不部署，也不上传附件到媒体桶。
SAP worker 与登录方式见 [接入说明](sap_computer_use.md)；限定三步查询见 [黄金路径](sap_golden_path.md)。

## 自行更新云端

1. Agent Engine 配置 `SAP_COMPUTER_USE_ENABLED=true`、`INVOICE_RECOGNITION_MODEL=gemini-3.8-flash`、
   `SAP_COMPUTER_USE_WORKER_URL=<受保护且云端可达的 HTTPS 地址>` 和至少 32 字符 `SAP_COMPUTER_USE_TOKEN`。
   主部署脚本从根 `.env` 读取并传递这些配置；本地 `env/local.env` 不会被部署脚本读取。
   A2A 部署入口也传递上述配置。令牌只配置在服务端。
   部署前会检查启用开关、HTTPS 地址与令牌；启用但仍填本机地址会停止部署。
2. SAP worker 独立配置 `SAP_COMPUTER_USE_GOLDEN_PATH=true`、`SAP_COMPUTER_USE_DEMO_MODE=computer-use`、
   SAP 应用完整 URL、相同令牌与 Vertex 模型访问权限。必须有可用浏览器环境；
   Agent Engine 无法访问你本机 `127.0.0.1`，代码更新不会自动解决 worker 联网与登录。
3. TSE 已有附件入口会将上传文件转成原生 `file_data`（`gs://` + MIME）。
   本次对接增加附件序号标记与合同测试；无需新增上传 API。
   Agent Engine 实际运行服务账号必须能读取 TSE 媒体桶（按需要授予 Storage Object Viewer）。
4. 在 TSE 当前用户身份绑定的 SAP 浏览器中亲自登录。独立 CLI 的 `adk:sap-demo`
   登录不会转给 `tse:<用户邮箱>`；CLI 可用 `--tse-email` 直接使用绑定的 TSE 用户会话。
   登录过期仍需人处理，当前没有远程登录直播界面。
5. 更新后用有明确 PO 标签的一页测试发票，先测仅识别，再测识别 → SAP → 截图。

本次仅修改代码和执行本地验证，未更新 Agent Engine、Cloud Run 或线上流量。

## 小智回复「没有 SAP 能力」的排查

已同步源码不代表当前 Agent Engine 启用了工具。本机 `env/local.env` 的配置仅影响本机；
根 `.env` 未开启 SAP 时，部署脚本会生成 `SAP_COMPUTER_USE_ENABLED=false`。
开关关闭会使 SAP 查询和发票识别工具不挂载。
新代码仍保留 `sap_prepare_browser` 连接诊断，用户说「连接 SAP」会得到当前部署未启用的说明。

在根 `.env` 配置完成后重新更新 SmartAgents Agent Engine，再在 TSE 点「新会话」重试。
不需要为了此开关修改 TSE 其他功能。只开开关而没有云端可达 worker/登录态，仍无法查询。
# 查询结果交付

SAP 查询工具返回后，固定 PoC 结果通过回调直接生成识别字段、原文证据与截图回复，
不再额外调用模型撰写收尾说明。失败、缺失订单号和等待登录也按真实工具结果交付。
TSE 在收到查询成功的工具事件时先显示识别字段，明确截图尚未交付；正式回复到达后替换预览。
这不增加供应商/金额自动核验或任何 SAP 写入能力。
