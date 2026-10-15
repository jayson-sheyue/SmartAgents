# SAP 黄金路径 PoC

固定闭环：直接打开采购订单应用 → 填入 4500071250 → Go → 返回真实结果截图。
本机已分别跑通两种模式，不打开单据详情、不搜索目录、不写入 SAP 业务数据。
发票图片/PDF 前置识别见 [发票 → SAP Demo](sap_invoice_demo.md)。

```bash
# 固定定位器模式（确定性浏览器脚本，不能把它宣传为模型自主操作）
.venvAgents/bin/python -m scripts.sap_golden_path --mode script
# Computer Use 模式：Gemini 只执行三步 click → type → click
.venvAgents/bin/python -m scripts.sap_golden_path --mode computer-use
```

默认用本项目专用 SAP 登录 Cookie，不读取原 Chrome 登录资料；仅复用 Cookie，不恢复旧应用缓存。
如果登录失效，加 `--login`，在打开的窗口亲自登录后按终端回车。
可用 `--url` 替换完整应用链接，`--order` 替换订单号，`--output` 指定截图文件。
默认页面：`https://your-tenant.s4hana.cloud.sap/ui?sap-language=en&help-mixedLanguages=false#PurchaseOrder-manage`。

SmartAgent 本地接入仍通过已有 worker，设置：

```dotenv
SAP_COMPUTER_USE_ENABLED=true
SAP_COMPUTER_USE_GOLDEN_PATH=true
SAP_COMPUTER_USE_DEMO_MODE=computer-use
```

输入「查询 SAP 采购订单 4500071250」，工具返回订单号与结果截图（ADK Artifact）。
如当前入口没有 Artifact 服务，会明确提示截图投递失败，可使用上面的独立脚本。
修改源码后需更新实际 SmartAgents Agent Engine 才生效；本机浏览器通过已认证的 HTTPS 节点连接。

演示话术：这个 PoC 没有为 SAP 新增业务接口，模型依据页面截图完成限定的查询操作。
它仍需要账号权限、浏览器执行环境和可访问的网络；不承诺所有 SAP 流程或通用页面均可自动完成。
小智新增发票图片/PDF识别工具：识别明确标注的采购订单号，再调用此黄金路径查询。
识别不到或包含多个订单号时暂停，请用户补充或选择。
