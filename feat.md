# Feature: 引入 Agent Gateway 实现云端 Agent 的安全管控

## 目标与背景
本项目原有的架构是通过前端 UI 发送请求到中转服务 `widget_server.py`，再由其直接调用 Google Cloud Reasoning Engine。
为了提升企业级安全防护（包括细粒度 IAP 授权、防止提示词注入、审计拦截等），我们决定引入 Google Cloud 的 **Agent Gateway** 机制。

## 架构理解与澄清
通过研读官方文档 `Agent Gateway Runtime Deploy`，我们确认了 Agent Gateway 的核心设计哲学：
- **并非暴露独立 Endpoint**：Agent Gateway 并不是一个有着独立 URL 域名的传统反向代理节点。
- **透明拦截与路由**：它是绑定在 Agent Runtime (Reasoning Engine) 的部署配置（`deploymentSpec`）上的一个网络策略对象。
- **客户端零改造**：调用方代码（`widget_server.py`）不需要改变请求的主机地址，依然向原本的 `aiplatform.googleapis.com/.../reasoningEngines/ID` 发起请求。GCP 底层基础设施会自动识别到该 Agent 绑定了 Gateway，从而将流量透明地重定向到 Gateway 执行安全策略。

## 所做改动
1. **代码回归云端调用模式**：将 `widget_server.py` 之前用于本地测试的 `AdkApp(agent=cloud_agent)` 直连模式移除。
2. **目标实例指向**：将目标请求 URL 指向了云端已部署的实例 `projects/839062387451/locations/us-central1/reasoningEngines/6587418803343196160`。
3. **API 版本升级**：为了更好地兼容处于 Private Preview 阶段的 Agent Gateway 新特性，在 `widget_server.py` 中将 REST 请求端点从 `v1` 调整为了 `v1beta1`。

## 实现效果
（目前由于项目级别权限限制，暂时将代码切回了直接从本地驱动 Agent 的可用状态）
原计划当运维在 GCP 上通过 PATCH API 将 `gateway-jayson` 绑定到该 Reasoning Engine 后：
1. **安全接管**：前端点击发送消息后，流量到达 GCP，在真正唤醒 LLM 大脑之前，会先经过 `gateway-jayson`。
2. **统一治理**：管理员可以直接在 Google Cloud 控制台为该 Gateway 附加 `Model Armor` 策略（清洗不安全输出）、配置 `Service Extensions` 等，而我们无需在 `widget_server.py` 里编写任何鉴权或清洗代码。