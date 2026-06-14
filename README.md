# AI-native 垂直能力服务平台

本项目不是传统网页工具，也不是单一视频制作产品。

核心方向是：把高价值垂直任务包装成可被智能体、CLI、MCP、工作流平台、Web 和企业 API 调用的服务单元。

文档拆分：

- [AI-native 垂直能力服务平台](docs/ai-native-service-platform.md)：只讲平台方法、服务单元、渠道和架构。
- [dreamina_cli_pool 技术闭环](docs/examples/dreamina-cli-pool.md)：封装官方 `dreamina` CLI，在原能力上增加多账号池。
- [story_to_pack 业务闭环](docs/examples/story-to-pack.md)：用“小说/剧本到 AI 漫剧前期制作包”说明后续业务服务单元。
- [开发说明](docs/development.md)：本地 API 和 CLI 的启动方式。

第一阶段先用 `dreamina_cli_pool` 验证真实 CLI 封装、账号池和智能体渠道。`story_to_pack` 是后续业务落地例子。

当前代码已经包含第一版本地闭环：

```text
Node.js + TypeScript CLI: apps/cli
Python FastAPI 本地服务: apps/api
SQLite 账号池: ~/.ainong/dreamina/pool.db
官方 Dreamina CLI: 通过独立 HOME 调用
```

本地启动见：[开发说明](docs/development.md)。
