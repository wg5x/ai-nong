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

## Runtime

This package is a local Node.js CLI. It manages the Dreamina account pool directly with local SQLite state:

```text
~/.ainong/dreamina/pool.db
```

No local API server is required.
