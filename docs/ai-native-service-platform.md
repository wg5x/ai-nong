# AI-native 垂直能力服务平台

## 核心判断

这个项目不是“视频制作工具”，而是一个 AI-native 垂直能力服务平台。

核心思路：

```text
高价值垂直任务
-> 标准输入
-> 标准输出
-> 后端生产服务
-> 账号与额度
-> 多渠道发布
-> 标准资源包交付
```

传统软件主要靠网页渠道：

```text
人
-> 打开网页
-> 学习 UI
-> 操作工具
-> 下载结果
```

AI-native 产品会增加智能体渠道：

```text
人
-> 告诉智能体目标
-> 智能体调用 Skill / MCP / CLI / API / 扣子 / Dify / FastGPT
-> 后端服务生产结果
-> 智能体把结果交还给人
```

网页不会消失，但网页从唯一入口变成众多入口之一。后端生产能力、账号额度、任务系统、成本核算和标准资源包才是产品核心。

## 产品定位

一句话定位：

> 可被智能体调用的 AI 垂直能力服务平台。

第一阶段不做通用能力市场，先用一个具体场景验证平台方法。

首个落地例子：

> 小说/剧本到 AI 漫剧前期制作包。

视频制作只是第一个验证场景，不是项目全部边界。选择它是因为这个场景有明确输入、明确产出、明确付费对象和清晰生产链路。

## 服务单元

每个能力都按“服务单元”设计。

一个服务单元必须定义：

1. 用户输入什么。
2. 服务产出什么。
3. 产出物能拿去做什么。
4. 消耗多少额度。
5. 如何验收质量。
6. 失败如何重试。
7. 可以通过哪些渠道调用。

第一批候选服务单元：

| 服务单元 | 输入 | 输出 | 目标用户 |
|---|---|---|---|
| `story_to_pack` | 小说/剧本文本 | 分镜表、角色卡、场景卡、关键帧、粗剪、资源包 | 漫剧/短剧团队 |
| `script_to_storyboard` | 剧本/文本片段 | 分镜表、镜头任务、prompt | 编剧、AI 操作员 |
| `character_to_reference_pack` | 角色描述/参考图 | 角色卡、多角度图、参考图、prompt | AI 绘图师、制作团队 |
| `shot_to_keyframe` | 镜头描述/角色图 | 镜头关键帧、图片 prompt | AI 视频创作者 |
| `keyframes_to_rough_cut` | 关键帧、字幕、时长 | 粗剪 MP4、项目 JSON | 剪辑、制片 |
| `hot_content_breakdown` | 爆款视频/剧本/链接 | 节奏表、爽点、钩子、结构拆解 | 编剧、策划、MCN |
| `ip_adaptation_eval` | 小说/IP 片段 | 改编潜力、风险、受众、成本估计 | IP 方、制片 |
| `proposal_pack` | 故事、角色图、分镜 | Markdown/PPT 提案、粗剪 Demo | 商务、IP 方 |
| `workflow_pack` | 分镜表/资产 | ComfyUI workflow、批量 prompt、任务清单 | AI 操作员 |

第一阶段只重点验证 `story_to_pack`，最多补一个轻量的 `character_to_reference_pack`。

## 落地例子：story_to_pack

`story_to_pack` 的目标不是直接生成发布级视频，而是把小说/剧本变成可评审、可分工、可继续生成的视频前期制作包。

输入：

```text
- 小说/剧本文本
- 画风
- 目标镜头数
- 输出类型
```

输出：

```text
package.zip
├── storyboard.md
├── characters.json
├── scenes.json
├── shots.csv
├── shots.json
├── prompts.json
├── assets/
│   ├── characters/
│   ├── scenes/
│   └── keyframes/
├── rough-cut.mp4
└── manifest.json
```

资源包价值：

```text
小说/剧本
-> 可评审的方向
-> 可报价的镜头清单
-> 可分工的生产任务
-> 可复用的角色/场景资产
-> 可继续图生视频的关键帧
-> 可用于提案的粗剪 Demo
```

类比软件项目：

| 软件项目 | 视频前期制作包 |
|---|---|
| PRD | 故事分析、剧本结构、角色关系、场景设定 |
| 架构设计 | 分集、分场、分镜结构 |
| 技术方案 | 画风、模型选择、prompt、参考图、生成参数 |
| UI 设计稿 | 角色基准图、场景图、镜头关键帧 |
| 任务分解 | 每个镜头的生成任务、剪辑任务、配音任务 |
| 原型 Demo | 粗剪视频 |
| 工期/预算评估 | 镜头数量、生成成本、返工次数、资产复用情况 |

准确卖点不是“一键生成视频”，而是：

> 把小说/剧本转成可开工的视频前期制作包。

## 渠道模型

渠道分成五类：

| 渠道类型 | 面向对象 | 主要作用 |
|---|---|---|
| 网页渠道 | 人 | 建立信任、展示案例、注册、支付、提交试跑、下载结果 |
| 智能体渠道 | Agent | 发现能力、理解参数、调用工具、检查产出、处理失败 |
| 工作流渠道 | Dify/FastGPT/扣子等平台 | 把能力嵌入用户已有流程 |
| 系统渠道 | 企业系统/API | 批量调用、私有化集成、自动化生产 |
| CLI 渠道 | 技术用户/内部交付团队 | 稳定执行、批处理、调试和交付 |

发布渠道矩阵：

| 渠道 | 类型 | 作用 | 优先级 |
|---|---|---|---|
| 后端 API | 系统渠道 | 核心生产服务，负责账号、额度、任务、资产和打包 | P0 |
| CLI | CLI 渠道 | 稳定执行入口，适合内部交付、技术型客户和批处理 | P0 |
| Codex Skill | 智能体渠道 | 让 Codex 用户和内部智能体知道如何调用 CLI/API 并验收结果 | P1 |
| MCP Server | 智能体渠道 | 跨智能体调用协议，后续接 ChatGPT、Claude、Cursor、VS Code 等 | P1 |
| Dify Tool / Workflow | 工作流渠道 | 文本拆解工作流或外部工具入口 | P1 |
| FastGPT OpenAPI / MCP | 工作流渠道 | 企业私有化、知识库和工作流入口 | P2 |
| 扣子 Bot / 插件 | 工作流渠道 | 国内普通用户 Bot 入口和演示获客入口 | P2 |
| 极简 Web | 网页渠道 | 案例展示、注册、提交试跑、下载结果 | P2 |
| 企业开放 API | 系统渠道 | 给制作公司、平台方接入内部系统 | P3 |

所有渠道都调用后端 API。渠道不能直接管理模型密钥、任务状态、资源包或扣费逻辑。

推荐链路：

```text
Codex Skill / MCP / CLI / 扣子 / Dify / FastGPT / Web
-> 后端 API
-> 鉴权和额度
-> 任务队列
-> 模型与工作流
-> 标准资源包
```

不推荐链路：

```text
扣子 -> Dify -> FastGPT -> ComfyUI -> Remotion -> 文件
```

原因是状态、额度、失败重试、资产回写和成本核算都会分散，难以产品化。

## 技术架构

```mermaid
flowchart TD
  CLI["CLI"] --> API["后端 API"]
  SK["Codex Skill"] --> CLI
  MCP["MCP Server"] --> API
  WEB["Web"] --> API
  COZE["扣子 Bot/插件"] --> API
  FG["FastGPT OpenAPI/MCP"] --> API
  DFY["Dify Tool/App"] --> API
  ENT["企业系统"] --> API

  API --> AUTH["账号/登录/额度/计费"]
  API --> DB["Postgres"]
  API --> S3["对象存储"]
  API --> Q["任务队列"]

  Q --> TEXT["文本工作流"]
  TEXT --> LLM["LLM Provider"]
  Q --> IMG["图片生成"]
  Q --> RENDER["粗剪/导出"]

  IMG --> S3
  RENDER --> S3
  Q --> DB
```

推荐 MVP 技术栈：

```text
CLI：Node.js / Python
后端：NestJS / Fastify / Next.js API
数据库：Postgres
对象存储：MinIO，后续可换 S3/OSS
队列：Redis + BullMQ
文本工作流：Dify，后续可迁移 LangGraph
文本模型：OpenAI / Qwen / DeepSeek / Hermes，通过 Provider 抽象接入
图片生成：ComfyUI 或第三方 Image API
视频合成：Remotion
MCP：Remote MCP Server
Web：Next.js，只做展示、注册、提交试跑和下载结果
```

## 核心对象

```text
users
api_tokens
service_units
projects
source_documents
assets
generation_tasks
packages
credit_records
channel_invocations
```

关键设计：

1. `service_units` 定义每个能力的输入、输出、额度、验收和渠道。
2. `channel_invocations` 记录来自 CLI、Skill、MCP、Web、扣子、Dify、FastGPT、API 的调用。
3. `packages` 保存标准资源包和 `manifest.json`。
4. `generation_tasks` 统一管理排队、执行、失败、重试和扣费。
5. `api_tokens` 只保存用户级 token，不保存供应商模型密钥。

## CLI 协议

第一阶段 CLI 是最稳定的执行入口。

建议命令：

```bash
ainong login
ainong run story_to_pack ./story.txt --style anime --max-shots 30
ainong status <job_id>
ainong export <project_id> --format zip
ainong check <package.zip>
```

CLI 负责：

- 登录和保存用户级 token。
- 上传文本。
- 创建服务单元任务。
- 查询状态。
- 下载资源包。
- 本地检查资源包完整性。

CLI 不负责：

- 内置供应商模型 token。
- 直接调用模型供应商。
- 保存服务端业务事实。

## Skill / MCP 协议

Skill 负责告诉智能体：

- 服务能做什么。
- 需要什么输入。
- 如何登录。
- 如何调用 CLI 或 API。
- 如何检查资源包是否完整。
- 失败时如何重试。

MCP 暴露标准工具：

```text
list_service_units
create_job
get_job_status
export_package
check_package
```

第一阶段可以把 `story_to_pack` 暴露成：

```text
create_story_pack
```

## 30 天计划

### 第 1 周：样板资源包

- 做 2-3 个 `story_to_pack` 样板。
- 明确 `package.zip` 目录结构。
- 明确 `manifest.json`。
- 明确资源包验收清单。

### 第 2 周：后端 API + CLI

- 账号。
- 用户级 token。
- 免费额度。
- 创建任务。
- 查询状态。
- 下载资源包。
- CLI 跑通 `story_to_pack`。

### 第 3 周：服务生产链路

- 文本拆解。
- 角色/场景/分镜生成。
- 图片生成。
- 粗剪导出。
- 资源包打包。

### 第 4 周：发布渠道验证

- Codex Skill。
- MCP Server。
- Dify Tool。
- FastGPT OpenAPI/MCP。
- 极简 Web。
- 找 5 个真实文本试跑。

30 天验证标准：

```text
5 个真实文本
2 个愿意付费或继续合作的客户
1 个能被 CLI/Skill/MCP 稳定调用的服务单元
1 套可复用的资源包协议
```

## 待验证问题

1. 第一阶段是否只验证 `story_to_pack`，还是同步做轻量 `character_to_reference_pack`？
2. 免费额度按字数、镜头数、图片数还是资源包次数限制？
3. 第一批发布渠道优先选 Codex Skill、Dify、FastGPT 还是扣子？
4. 用户最愿意为分镜表、图片素材包、粗剪视频还是提案包付费？
5. 是否已有账号、额度、项目和资产系统可复用？
6. 哪个服务单元能最快产生付费验证？

## 参考

- Model Context Protocol：`https://modelcontextprotocol.io`
- Codex Skills：`https://developers.openai.com/codex/skills`
- Dify：`https://github.com/langgenius/dify`
- FastGPT：`https://github.com/labring/FastGPT`
- Coze：`https://www.coze.com`
- ComfyUI：`https://github.com/comfy-org/comfyui`
- Remotion：`https://github.com/remotion-dev/remotion`
