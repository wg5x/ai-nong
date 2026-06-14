import { spawn } from "node:child_process";
import { mkdirSync, renameSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { downloadDir, dreaminaCommand } from "./settings.js";
import {
  accountIdFromProviderUserId,
  extractSubmitId,
  findVideoUrl,
  normalizeDreaminaStatus,
  parseJsonPayload,
  parseLoginOutput,
  providerUserIdFromCredit,
} from "./dreamina-utils.js";
import { DreaminaPool } from "./pool.js";

const GENERATION_COMMANDS = new Set(["text2video", "image2video", "frames2video"]);

type DreaminaResult = {
  code: number;
  stdout: string;
  stderr: string;
};

export async function runDreamina(args: string[], homeDir: string): Promise<DreaminaResult> {
  mkdirSync(homeDir, { recursive: true });
  return new Promise((resolve, reject) => {
    const child = spawn(dreaminaCommand(), args, {
      env: { ...process.env, HOME: homeDir },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 0, stdout, stderr });
    });
  });
}

export class DreaminaService {
  pool: DreaminaPool;

  constructor(pool = new DreaminaPool()) {
    this.pool = pool;
  }

  nextAccountId(): string {
    const used = this.pool.usedLoginAccountIds();
    let index = 1;
    while (true) {
      const accountId = `account-${String(index).padStart(3, "0")}`;
      if (!used.has(accountId)) {
        return accountId;
      }
      index += 1;
    }
  }

  async startLogin(): Promise<Record<string, unknown>> {
    this.pool.ensure();
    const accountId = this.nextAccountId();
    const sessionId = randomUUID().replaceAll("-", "");
    const homeDir = join(this.pool.accountsDir, accountId);
    rmSync(homeDir, { recursive: true, force: true });
    mkdirSync(homeDir, { recursive: true });

    const result = await runDreamina(["login", "--headless"], homeDir);
    if (result.code !== 0) {
      throw new Error(result.stderr.trim() || result.stdout.trim() || "dreamina login failed");
    }
    const parsed = parseLoginOutput(result.stdout);
    const session = this.pool.createLoginSession({
      sessionId,
      accountId,
      homeDir,
      verificationUri: parsed.verification_uri,
      userCode: parsed.user_code || "",
      deviceCode: parsed.device_code,
      expiresAt: parsed.expires_at,
      stdout: result.stdout,
      stderr: result.stderr,
    });
    return {
      ...session,
      next: `Open ${parsed.verification_uri} and enter code ${parsed.user_code || ""}, then run \`ainong login check ${sessionId}\`.`,
    };
  }

  async checkLogin(sessionId: string): Promise<Record<string, unknown>> {
    const row = this.pool.loginSessionInternal(sessionId);
    if (!row) {
      throw new Error("登录会话不存在");
    }
    if (row.status === "succeeded") {
      return this.pool.loginSession(sessionId) || {};
    }
    if (isExpired(row.expires_at)) {
      this.pool.markLoginSession(sessionId, "expired", { error: "登录授权已过期" });
      return this.pool.loginSession(sessionId) || {};
    }

    const homeDir = String(row.home_dir);
    const result = await runDreamina(
      ["login", "checklogin", `--device_code=${String(row.device_code)}`, "--poll=1"],
      homeDir,
    );
    const output = `${result.stdout}\n${result.stderr}`.trim();
    if (result.code !== 0) {
      if (output.includes("等待登录超时") || output.toLowerCase().includes("timeout")) {
        this.pool.markLoginSession(sessionId, "pending", { stdout: result.stdout, stderr: result.stderr });
        return this.pool.loginSession(sessionId) || {};
      }
      this.pool.markLoginSession(sessionId, "failed", {
        error: output || "登录失败",
        stdout: result.stdout,
        stderr: result.stderr,
      });
      return this.pool.loginSession(sessionId) || {};
    }

    const credit = await this.readCredit(homeDir);
    const providerUserId = providerUserIdFromCredit(credit);
    const finalAccountId = accountIdFromProviderUserId(providerUserId, String(row.account_id));
    const existingFinalAccount = this.pool.accountRow(finalAccountId);
    if (existingFinalAccount && finalAccountId !== row.account_id) {
      this.pool.markLoginSession(sessionId, "failed", {
        providerUserId,
        accountId: String(existingFinalAccount.id),
        error: `该 Dreamina 用户已在账号池中：${String(existingFinalAccount.id)}`,
        stdout: result.stdout,
        stderr: result.stderr,
      });
      return this.pool.loginSession(sessionId) || {};
    }

    const duplicate = await this.findDuplicateProviderUser(providerUserId, finalAccountId);
    if (duplicate && duplicate.id !== finalAccountId) {
      this.pool.markLoginSession(sessionId, "failed", {
        providerUserId,
        accountId: String(duplicate.id),
        error: `该 Dreamina 用户已在账号池中：${String(duplicate.id)}`,
        stdout: result.stdout,
        stderr: result.stderr,
      });
      return this.pool.loginSession(sessionId) || {};
    }

    const accountHome = this.promoteLoginHome(homeDir, String(row.account_id), finalAccountId);
    const account = this.pool.registerAccount({
      accountId: finalAccountId,
      homeDir: accountHome,
      providerUserId: providerUserId || null,
      creditSnapshot: credit,
    });
    this.pool.markLoginSession(sessionId, "succeeded", {
      providerUserId,
      accountId: account.id,
      stdout: result.stdout,
      stderr: result.stderr,
    });
    return this.pool.loginSession(sessionId) || {};
  }

  async submitTask(command: string, args: string[]): Promise<Record<string, unknown>> {
    if (!GENERATION_COMMANDS.has(command)) {
      throw new Error(`Unsupported Dreamina command: ${command}`);
    }
    for (const account of this.pool.activeAccounts()) {
      const fd = this.pool.tryLockAccount(account);
      if (fd === null) {
        continue;
      }
      this.pool.markAccountUsed(account.id);
      try {
        const result = await runDreamina([command, ...args], account.home_dir);
        const parsed = parseJsonPayload(result.stdout);
        const providerTaskId = extractSubmitId(result.stdout);
        const taskId = providerTaskId || randomUUID().replaceAll("-", "");
        const status = result.code === 0 && providerTaskId ? "submitted" : "failed";
        this.pool.upsertTask({
          taskId,
          accountId: account.id,
          command,
          args,
          status,
          stdout: result.stdout,
          stderr: result.stderr,
          providerTaskId,
          resultJson: parsed,
        });
        if (result.code !== 0 || !providerTaskId) {
          this.pool.markAccountError(account.id, result.stderr || result.stdout);
        }
        return {
          task_id: taskId,
          provider_task_id: providerTaskId,
          account_id: account.id,
          status,
          stdout: result.stdout,
          stderr: result.stderr,
        };
      } finally {
        this.pool.releaseLock(account, fd);
      }
    }
    throw new Error("No available active Dreamina account. Run `ainong login` first.");
  }

  async getTask(taskId: string): Promise<Record<string, unknown>> {
    const task = this.pool.task(taskId);
    if (!task) {
      throw new Error("Task not found");
    }
    const providerTaskId = task.provider_task_id;
    if (!providerTaskId) {
      return task;
    }
    const account = this.pool.taskAccount(taskId);
    if (!account) {
      return task;
    }

    const targetDir = downloadDir();
    mkdirSync(targetDir, { recursive: true });
    const result = await runDreamina(
      ["query_result", `--submit_id=${String(providerTaskId)}`, `--download_dir=${targetDir}`],
      account.home_dir,
    );
    const parsed = parseJsonPayload(result.stdout);
    if (result.code !== 0) {
      return {
        ...task,
        query_error: result.stderr.trim() || result.stdout.trim(),
      };
    }

    const status = normalizeDreaminaStatus(parsed?.gen_status);
    const args = parseArgsJson(task.args_json);
    this.pool.upsertTask({
      taskId,
      accountId: account.id,
      command: String(task.command),
      args,
      status,
      stdout: result.stdout,
      stderr: result.stderr,
      providerTaskId: String(providerTaskId),
      resultJson: parsed,
    });
    return {
      ...(this.pool.task(taskId) || task),
      video_url: findVideoUrl(parsed),
    };
  }

  async refreshCredit(accountId: string): Promise<Record<string, unknown> | null> {
    const account = this.pool.accountRow(accountId);
    if (!account) {
      return null;
    }
    let credit = await this.readCredit(String(account.home_dir));
    const providerUserId = providerUserIdFromCredit(credit);
    const duplicate = await this.findDuplicateProviderUser(providerUserId, accountId);
    let lastError: string | null = null;
    let providerUserIdToStore: string | null = providerUserId || null;
    if (duplicate && duplicate.id !== accountId) {
      lastError = `该 Dreamina 用户已在账号池中：${String(duplicate.id)}`;
      credit = null;
      providerUserIdToStore = null;
    }
    this.pool.updateAccountCredit({
      accountId,
      providerUserId: providerUserIdToStore,
      creditSnapshot: credit,
      lastError,
      disable: Boolean(lastError),
    });
    return credit;
  }

  updateAccountStatus(accountId: string, status: string): Record<string, unknown> | null {
    if (status !== "active" && status !== "disabled") {
      throw new Error("status must be active or disabled");
    }
    return this.pool.updateAccountStatus(accountId, status);
  }

  private async readCredit(homeDir: string): Promise<Record<string, unknown> | null> {
    const result = await runDreamina(["user_credit"], homeDir);
    return result.code === 0 ? parseJsonPayload(result.stdout) : null;
  }

  private promoteLoginHome(homeDir: string, accountId: string, finalAccountId: string): string {
    if (finalAccountId === accountId) {
      return homeDir;
    }
    const finalHomeDir = join(this.pool.accountsDir, finalAccountId);
    rmSync(finalHomeDir, { recursive: true, force: true });
    renameSync(homeDir, finalHomeDir);
    return finalHomeDir;
  }

  private async findDuplicateProviderUser(
    providerUserId: string,
    currentAccountId: string,
  ): Promise<Record<string, unknown> | null> {
    const duplicate = this.pool.accountByProviderUserId(providerUserId);
    if (duplicate && duplicate.id !== currentAccountId) {
      return duplicate;
    }
    if (!providerUserId) {
      return null;
    }
    const canStoreMatchingUnmarkedAccount = duplicate === null;

    for (const account of this.pool.accountsWithoutProviderUserId()) {
      if (account.id === currentAccountId) {
        continue;
      }
      const credit = await this.readCredit(String(account.home_dir));
      const discoveredProviderUserId = providerUserIdFromCredit(credit);
      if (!discoveredProviderUserId) {
        continue;
      }
      if (discoveredProviderUserId === providerUserId) {
        if (duplicate && duplicate.id === currentAccountId) {
          this.pool.updateAccountCredit({
            accountId: String(account.id),
            providerUserId: null,
            creditSnapshot: null,
            lastError: `该 Dreamina 用户已在账号池中：${currentAccountId}`,
            disable: true,
          });
          continue;
        }
        if (canStoreMatchingUnmarkedAccount) {
          this.pool.updateAccountCredit({
            accountId: String(account.id),
            providerUserId: discoveredProviderUserId,
            creditSnapshot: credit,
            lastError: null,
          });
          return this.pool.accountRow(String(account.id));
        }
        return account;
      }
      const discoveredDuplicate = this.pool.accountByProviderUserId(discoveredProviderUserId);
      if (discoveredDuplicate && discoveredDuplicate.id !== account.id) {
        continue;
      }
      this.pool.updateAccountCredit({
        accountId: String(account.id),
        providerUserId: discoveredProviderUserId,
        creditSnapshot: credit,
        lastError: null,
      });
    }
    return null;
  }
}

function isExpired(expiresAt: unknown): boolean {
  if (!expiresAt) {
    return false;
  }
  const expires = Date.parse(String(expiresAt));
  return Number.isFinite(expires) && expires < Date.now();
}

function parseArgsJson(value: unknown): string[] {
  try {
    const parsed = JSON.parse(String(value || "[]"));
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}
