# ainong

Dreamina-compatible CLI wrapper with account-pool support.

## Install

```bash
npm install -g ainong
```

The official `dreamina` CLI must be installed separately:

```bash
curl -fsSL https://jimeng.jianying.com/cli | bash
dreamina --help
```

## Commands

```bash
ainong doctor
ainong accounts
ainong login
ainong login check <session_id>
ainong text2video --prompt "古风少女，月下庭院"
ainong image2video --image ./input.png --prompt "镜头缓慢推进"
ainong frames2video --first ./first.png --last ./last.png --prompt "角色转身"
ainong status <task_id>
```

## Current Runtime

This package provides the Node.js CLI. Commands that manage accounts or tasks call the local Ainong API at:

```text
http://127.0.0.1:8765
```

Set a different API endpoint with:

```bash
AINONG_API_URL=http://127.0.0.1:8765 ainong accounts
```

The local Python API is currently developed in the main repository. A future release should add `ainong serve` or a packaged daemon so `npm install -g ainong` becomes a complete one-command install.
