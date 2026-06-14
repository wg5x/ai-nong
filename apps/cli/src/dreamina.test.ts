import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { DreaminaService } from "./dreamina.js";
import { DreaminaPool } from "./pool.js";

function writeFakeDreamina(path: string): void {
  writeFileSync(
    path,
    `#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  login)
    if [[ "\${2:-}" == "--headless" ]]; then
      echo "verification_uri: https://jimeng.example/cli-auth"
      echo "user_code: user-code-123"
      echo "device_code: device-code-secret"
      echo "poll_interval: 1s"
      echo "expires_at: 2099-06-05T13:55:56Z"
      exit 0
    fi
    if [[ "\${2:-}" == "checklogin" ]]; then
      echo "OAuth 登录成功。"
      exit 0
    fi
    ;;
  user_credit)
    echo '{"total_credit":6201,"user_id":98321338731792,"vip_level":"maestro"}'
    exit 0
    ;;
  text2video)
    echo '{"submit_id":"submit-cli-123","gen_status":"querying","credit_count":25}'
    exit 0
    ;;
  query_result)
    download_dir=""
    submit_id=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --download_dir=*)
          download_dir="\${1#--download_dir=}"; shift ;;
        --submit_id=*)
          submit_id="\${1#--submit_id=}"; shift ;;
        --download_dir)
          download_dir="$2"; shift 2 ;;
        --submit_id)
          submit_id="$2"; shift 2 ;;
        *)
          shift ;;
      esac
    done
    mkdir -p "$download_dir"
    video_path="$download_dir/\${submit_id}.mp4"
    printf 'fake mp4' > "$video_path"
    printf '{"submit_id":"%s","gen_status":"success","result_json":{"videos":[{"path":"%s"}]}}\\n' "$submit_id" "$video_path"
    exit 0
    ;;
esac
echo "unsupported $*" >&2
exit 2
`,
    { encoding: "utf8", mode: 0o755 },
  );
}

describe("DreaminaService", () => {
  it("promotes a login session to provider_user_id account", async () => {
    const tmp = join(tmpdir(), `ainong-test-${randomUUID()}`);
    mkdirSync(tmp, { recursive: true });
    const fakeDreamina = join(tmp, "dreamina");
    writeFakeDreamina(fakeDreamina);
    process.env.DREAMINA_COMMAND = fakeDreamina;

    const pool = new DreaminaPool(join(tmp, "pool"));
    const service = new DreaminaService(pool);
    const session = await service.startLogin();

    expect(session.account_id).toBe("account-001");
    expect(session.verification_uri).toBe("https://jimeng.example/cli-auth");
    expect(session.user_code).toBe("user-code-123");
    expect(session.status).toBe("pending");
    expect(session).not.toHaveProperty("device_code");

    const checked = await service.checkLogin(String(session.id));
    expect(checked.status).toBe("succeeded");
    expect(checked.account_id).toBe("98321338731792");

    const accounts = pool.listAccounts();
    expect(accounts).toHaveLength(1);
    expect(accounts[0].id).toBe("98321338731792");
    expect(accounts[0].provider_user_id).toBe("98321338731792");
    expect((accounts[0].credit as Record<string, unknown>).total_credit).toBe(6201);
  });

  it("rejects duplicate provider users", async () => {
    const tmp = join(tmpdir(), `ainong-test-${randomUUID()}`);
    mkdirSync(tmp, { recursive: true });
    const fakeDreamina = join(tmp, "dreamina");
    writeFakeDreamina(fakeDreamina);
    process.env.DREAMINA_COMMAND = fakeDreamina;

    const pool = new DreaminaPool(join(tmp, "pool"));
    const service = new DreaminaService(pool);
    const first = await service.startLogin();
    expect((await service.checkLogin(String(first.id))).status).toBe("succeeded");

    const second = await service.startLogin();
    const secondChecked = await service.checkLogin(String(second.id));

    expect(secondChecked.status).toBe("failed");
    expect(String(secondChecked.last_error)).toContain("98321338731792");
    expect(pool.listAccounts()).toHaveLength(1);
  });

  it("submits and queries with the original account", async () => {
    const tmp = join(tmpdir(), `ainong-test-${randomUUID()}`);
    mkdirSync(tmp, { recursive: true });
    const fakeDreamina = join(tmp, "dreamina");
    writeFakeDreamina(fakeDreamina);
    process.env.DREAMINA_COMMAND = fakeDreamina;
    process.env.AINONG_DOWNLOAD_DIR = join(tmp, "downloads");

    const pool = new DreaminaPool(join(tmp, "pool"));
    const accountHome = join(tmp, "pool", "accounts", "98321338731792");
    mkdirSync(accountHome, { recursive: true });
    pool.ensure();
    const db = pool.connect();
    try {
      db.prepare(
        `INSERT INTO accounts (
           id, provider_user_id, home_dir, status, created_at, updated_at
         ) VALUES ('98321338731792', '98321338731792', ?, 'active', '2026-01-01T00:00:00', '2026-01-01T00:00:00')`,
      ).run(accountHome);
    } finally {
      db.close();
    }

    const service = new DreaminaService(pool);
    const submitted = await service.submitTask("text2video", ["--prompt", "test prompt"]);
    expect(submitted.task_id).toBe("submit-cli-123");
    expect(submitted.account_id).toBe("98321338731792");

    const status = await service.getTask("submit-cli-123");
    expect(status.status).toBe("succeeded");
    expect(String(status.video_url)).toMatch(/submit-cli-123\.mp4$/);
  });
});
