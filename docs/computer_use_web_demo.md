# 无需登录的商城 Computer Use 演示

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
