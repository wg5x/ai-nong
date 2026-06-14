# 本地开发说明

## 安装依赖

```bash
pnpm install
python3 -m venv .venv
. .venv/bin/activate
pip install -r apps/api/requirements.txt
```

## 检查 Dreamina

官方 `dreamina` CLI 需要单独安装：

```bash
curl -fsSL https://jimeng.jianying.com/cli | bash
dreamina --help
```

## 启动本地 API

```bash
. .venv/bin/activate
uvicorn ainong_api.main:app --app-dir apps/api --reload --port 8765
```

## 运行 CLI

```bash
pnpm cli -- doctor
pnpm cli -- accounts
```

## 登录流程

`ainong login` 会分配一个临时账号目录，例如 `accounts/account-001`，并用该独立 `HOME` 调用官方 `dreamina login --headless`，返回 `verification_uri`、`user_code` 和 `session_id`。

```bash
pnpm cli -- login
```

用户完成授权后，执行：

```bash
pnpm cli -- login check <session_id>
```

检查成功后，后端会调用 `dreamina user_credit` 读取真实 `provider_user_id`，并把临时账号目录晋升到：

```text
~/.ainong/dreamina/accounts/{provider_user_id}/
```

## 生成和查询

以下命令会消耗 Dreamina 额度，开发验证前要确认：

```bash
pnpm cli -- text2video --prompt "古风少女，月下庭院"
pnpm cli -- image2video --image ./input.png --prompt "镜头缓慢推进"
pnpm cli -- frames2video --first ./first.png --last ./last.png --prompt "角色转身"
```

生成成功后，`task_id` 默认使用官方返回的 `submit_id`：

```bash
pnpm cli -- status <task_id>
```

`status` 会根据本地任务表找到原账号，再用该账号的独立 `HOME` 调官方 `dreamina query_result`。

## 当前边界

已实现：

```text
Node.js + TypeScript CLI
Python FastAPI 本地服务
SQLite 账号池
Dreamina 登录会话
provider_user_id 入池
账号 HOME 隔离
单账号文件锁
text2video / image2video / frames2video 透传
status 回原账号查询
账号 refresh / active / disabled 管理
fake Dreamina 行为测试
```

暂未实现：

```text
全局 npm 发布
package.zip 打包
资源包 check
Web
MCP
多机器调度
```

## 发布 npm

包名 `ainong` 用于发布 CLI：

```bash
npm login
pnpm pack:cli
pnpm publish:cli
```

注意：当前 npm 包只包含 Node.js CLI。账号池 API 仍需要本地启动：

```bash
. .venv/bin/activate
uvicorn ainong_api.main:app --app-dir apps/api --port 8765
```

要让外部用户做到真正的一条命令可用，下一步需要补 `ainong serve`，由 CLI 自动启动或安装本地 Python API。
