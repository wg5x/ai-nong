import { DatabaseSync } from "node:sqlite";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { dreaminaBaseDir, lockTtlSeconds } from "./settings.js";

export type Account = {
  id: string;
  provider_user_id: string | null;
  home_dir: string;
  status: string;
  last_used_at: string | null;
};

type SqlRow = Record<string, unknown>;

export class DreaminaPool {
  baseDir: string;
  accountsDir: string;
  loginSessionsDir: string;
  dbPath: string;

  constructor(baseDir = dreaminaBaseDir()) {
    this.baseDir = baseDir;
    this.accountsDir = join(this.baseDir, "accounts");
    this.loginSessionsDir = join(this.baseDir, "login_sessions");
    this.dbPath = join(this.baseDir, "pool.db");
  }

  ensure(): void {
    mkdirSync(this.accountsDir, { recursive: true });
    mkdirSync(this.loginSessionsDir, { recursive: true });
    const db = this.connect();
    try {
      db.exec(`
        CREATE TABLE IF NOT EXISTS accounts (
          id TEXT PRIMARY KEY,
          provider_user_id TEXT UNIQUE,
          display_name TEXT,
          home_dir TEXT NOT NULL,
          status TEXT NOT NULL,
          last_used_at TEXT,
          last_alive_at TEXT,
          credit_snapshot_json TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          provider_task_id TEXT,
          account_id TEXT NOT NULL,
          command TEXT NOT NULL,
          args_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL,
          stdout TEXT NOT NULL DEFAULT '',
          stderr TEXT NOT NULL DEFAULT '',
          result_json TEXT,
          package_path TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_sessions (
          id TEXT PRIMARY KEY,
          account_id TEXT NOT NULL,
          home_dir TEXT NOT NULL,
          provider_user_id TEXT,
          status TEXT NOT NULL,
          verification_uri TEXT,
          user_code TEXT,
          device_code TEXT,
          expires_at TEXT,
          stdout TEXT NOT NULL DEFAULT '',
          stderr TEXT NOT NULL DEFAULT '',
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_dreamina_accounts_provider_user_id
        ON accounts(provider_user_id)
        WHERE provider_user_id IS NOT NULL AND provider_user_id <> '';
      `);
    } finally {
      db.close();
    }
  }

  connect(): DatabaseSync {
    mkdirSync(this.baseDir, { recursive: true });
    const db = new DatabaseSync(this.dbPath);
    db.exec("PRAGMA busy_timeout = 5000");
    return db;
  }

  listAccounts(): Record<string, unknown>[] {
    this.ensure();
    const db = this.connect();
    try {
      return db
        .prepare(
          `SELECT id, provider_user_id, display_name, home_dir, status,
                  last_used_at, last_alive_at, credit_snapshot_json,
                  last_error, created_at, updated_at
           FROM accounts
           ORDER BY COALESCE(last_used_at, ''), id`,
        )
        .all()
        .map((row) => {
          const item = row as SqlRow;
          const creditJson = item.credit_snapshot_json;
          delete item.credit_snapshot_json;
          item.credit = parseJsonOrNull(creditJson);
          return item;
        });
    } finally {
      db.close();
    }
  }

  usedLoginAccountIds(): Set<string> {
    this.ensure();
    const db = this.connect();
    try {
      const rows = db
        .prepare(
          `SELECT id FROM accounts
           UNION
           SELECT account_id AS id
           FROM login_sessions
           WHERE status IN ('pending', 'succeeded')
           ORDER BY id`,
        )
        .all() as SqlRow[];
      return new Set(rows.map((row) => String(row.id)).filter(Boolean));
    } finally {
      db.close();
    }
  }

  createLoginSession(input: {
    sessionId: string;
    accountId: string;
    homeDir: string;
    verificationUri: string;
    userCode: string;
    deviceCode: string;
    expiresAt?: string;
    stdout: string;
    stderr: string;
  }): Record<string, unknown> {
    this.ensure();
    const now = isoNow();
    const db = this.connect();
    try {
      db.prepare(
        `INSERT INTO login_sessions (
           id, account_id, home_dir, status, verification_uri, user_code,
           device_code, expires_at, stdout, stderr, created_at, updated_at
         ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)`,
      ).run(
        input.sessionId,
        input.accountId,
        input.homeDir,
        input.verificationUri,
        input.userCode,
        input.deviceCode,
        input.expiresAt || null,
        input.stdout,
        input.stderr,
        now,
        now,
      );
    } finally {
      db.close();
    }
    return this.loginSession(input.sessionId) || {};
  }

  loginSession(sessionId: string): Record<string, unknown> | null {
    this.ensure();
    const db = this.connect();
    try {
      const row = db
        .prepare(
          `SELECT id, account_id, home_dir, provider_user_id, status,
                  verification_uri, user_code, expires_at, last_error,
                  created_at, updated_at
           FROM login_sessions
           WHERE id = ?`,
        )
        .get(sessionId);
      return row ? (row as SqlRow) : null;
    } finally {
      db.close();
    }
  }

  loginSessionInternal(sessionId: string): Record<string, unknown> | null {
    this.ensure();
    const db = this.connect();
    try {
      const row = db.prepare("SELECT * FROM login_sessions WHERE id = ?").get(sessionId);
      return row ? (row as SqlRow) : null;
    } finally {
      db.close();
    }
  }

  markLoginSession(
    sessionId: string,
    status: string,
    input: {
      providerUserId?: string | null;
      accountId?: string | null;
      error?: string | null;
      stdout?: string | null;
      stderr?: string | null;
    } = {},
  ): void {
    const db = this.connect();
    try {
      db.prepare(
        `UPDATE login_sessions
         SET status = ?,
             provider_user_id = COALESCE(?, provider_user_id),
             account_id = COALESCE(?, account_id),
             stdout = COALESCE(?, stdout),
             stderr = COALESCE(?, stderr),
             last_error = ?,
             updated_at = ?
         WHERE id = ?`,
      ).run(
        status,
        input.providerUserId ?? null,
        input.accountId ?? null,
        input.stdout ?? null,
        input.stderr ?? null,
        input.error ?? null,
        isoNow(),
        sessionId,
      );
    } finally {
      db.close();
    }
  }

  activeAccounts(): Account[] {
    this.ensure();
    const db = this.connect();
    try {
      return db
        .prepare(
          `SELECT id, provider_user_id, home_dir, status, last_used_at
           FROM accounts
           WHERE status = 'active'
           ORDER BY COALESCE(last_used_at, ''), id`,
        )
        .all() as Account[];
    } finally {
      db.close();
    }
  }

  upsertTask(input: {
    taskId: string;
    accountId: string;
    command: string;
    args: string[];
    status: string;
    stdout?: string;
    stderr?: string;
    providerTaskId?: string | null;
    resultJson?: Record<string, unknown> | null;
  }): void {
    const now = isoNow();
    const db = this.connect();
    try {
      db.prepare(
        `INSERT INTO tasks (
           id, provider_task_id, account_id, command, args_json, status,
           stdout, stderr, result_json, created_at, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           provider_task_id = excluded.provider_task_id,
           account_id = excluded.account_id,
           command = excluded.command,
           args_json = excluded.args_json,
           status = excluded.status,
           stdout = excluded.stdout,
           stderr = excluded.stderr,
           result_json = excluded.result_json,
           updated_at = excluded.updated_at`,
      ).run(
        input.taskId,
        input.providerTaskId || null,
        input.accountId,
        input.command,
        JSON.stringify(input.args),
        input.status,
        input.stdout || "",
        input.stderr || "",
        input.resultJson ? JSON.stringify(input.resultJson) : null,
        now,
        now,
      );
    } finally {
      db.close();
    }
  }

  task(taskId: string): Record<string, unknown> | null {
    this.ensure();
    const db = this.connect();
    try {
      const row = db.prepare("SELECT * FROM tasks WHERE id = ?").get(taskId);
      return row ? (row as SqlRow) : null;
    } finally {
      db.close();
    }
  }

  taskAccount(taskId: string): Account | null {
    this.ensure();
    const db = this.connect();
    try {
      const row = db
        .prepare(
          `SELECT a.id, a.provider_user_id, a.home_dir, a.status, a.last_used_at
           FROM tasks t
           JOIN accounts a ON a.id = t.account_id
           WHERE t.id = ?`,
        )
        .get(taskId);
      return row ? (row as Account) : null;
    } finally {
      db.close();
    }
  }

  markAccountUsed(accountId: string): void {
    const now = isoNow();
    const db = this.connect();
    try {
      db.prepare("UPDATE accounts SET last_used_at = ?, last_error = NULL, updated_at = ? WHERE id = ?").run(
        now,
        now,
        accountId,
      );
    } finally {
      db.close();
    }
  }

  markAccountError(accountId: string, error: string): void {
    const db = this.connect();
    try {
      db.prepare("UPDATE accounts SET last_error = ?, updated_at = ? WHERE id = ?").run(error, isoNow(), accountId);
    } finally {
      db.close();
    }
  }

  accountByProviderUserId(providerUserId: string): Record<string, unknown> | null {
    if (!providerUserId) {
      return null;
    }
    this.ensure();
    const db = this.connect();
    try {
      const row = db.prepare("SELECT * FROM accounts WHERE provider_user_id = ?").get(providerUserId);
      return row ? (row as SqlRow) : null;
    } finally {
      db.close();
    }
  }

  accountRow(accountId: string): Record<string, unknown> | null {
    this.ensure();
    const db = this.connect();
    try {
      const row = db.prepare("SELECT * FROM accounts WHERE id = ?").get(accountId);
      return row ? (row as SqlRow) : null;
    } finally {
      db.close();
    }
  }

  accountsWithoutProviderUserId(): Record<string, unknown>[] {
    this.ensure();
    const db = this.connect();
    try {
      return db
        .prepare(
          `SELECT *
           FROM accounts
           WHERE provider_user_id IS NULL OR provider_user_id = ''
           ORDER BY id`,
        )
        .all() as SqlRow[];
    } finally {
      db.close();
    }
  }

  registerAccount(input: {
    accountId: string;
    homeDir: string;
    providerUserId?: string | null;
    displayName?: string | null;
    creditSnapshot?: Record<string, unknown> | null;
  }): Account {
    const now = isoNow();
    const db = this.connect();
    try {
      db.prepare(
        `INSERT INTO accounts (
           id, provider_user_id, display_name, home_dir, status,
           last_alive_at, credit_snapshot_json, created_at, updated_at
         ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           display_name = excluded.display_name,
           home_dir = excluded.home_dir,
           status = 'active',
           last_alive_at = excluded.last_alive_at,
           provider_user_id = COALESCE(excluded.provider_user_id, accounts.provider_user_id),
           credit_snapshot_json = excluded.credit_snapshot_json,
           last_error = NULL,
           updated_at = excluded.updated_at`,
      ).run(
        input.accountId,
        input.providerUserId || null,
        input.displayName || null,
        input.homeDir,
        now,
        input.creditSnapshot ? JSON.stringify(input.creditSnapshot) : null,
        now,
        now,
      );
    } finally {
      db.close();
    }
    return {
      id: input.accountId,
      provider_user_id: input.providerUserId || null,
      home_dir: input.homeDir,
      status: "active",
      last_used_at: null,
    };
  }

  updateAccountCredit(input: {
    accountId: string;
    providerUserId?: string | null;
    creditSnapshot?: Record<string, unknown> | null;
    lastError?: string | null;
    disable?: boolean;
  }): void {
    const now = isoNow();
    const db = this.connect();
    try {
      db.prepare(
        `UPDATE accounts
         SET last_alive_at = CASE WHEN ? THEN ? ELSE last_alive_at END,
             status = CASE WHEN ? THEN 'disabled' ELSE status END,
             provider_user_id = COALESCE(?, provider_user_id),
             credit_snapshot_json = COALESCE(?, credit_snapshot_json),
             last_error = ?,
             updated_at = ?
         WHERE id = ?`,
      ).run(
        input.lastError ? 0 : 1,
        now,
        input.disable ? 1 : 0,
        input.providerUserId || null,
        input.creditSnapshot ? JSON.stringify(input.creditSnapshot) : null,
        input.lastError || null,
        now,
        input.accountId,
      );
    } finally {
      db.close();
    }
  }

  updateAccountStatus(accountId: string, status: string): Record<string, unknown> | null {
    const db = this.connect();
    try {
      db.prepare("UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?").run(status, isoNow(), accountId);
    } finally {
      db.close();
    }
    return this.accountRow(accountId);
  }

  accountLockPath(account: Account): string {
    return join(account.home_dir, ".ainong.lock");
  }

  tryLockAccount(account: Account): number | null {
    mkdirSync(account.home_dir, { recursive: true });
    const lockPath = this.accountLockPath(account);
    for (let index = 0; index < 2; index += 1) {
      try {
        const fd = openSync(lockPath, "wx");
        writeFileSync(
          fd,
          JSON.stringify({
            pid: process.pid,
            provider_user_id: account.provider_user_id,
            created_at: isoNow(),
          }),
        );
        return fd;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
          throw error;
        }
        cleanupStaleLock(lockPath);
      }
    }
    return null;
  }

  releaseLock(account: Account, fd: number): void {
    try {
      closeSync(fd);
    } catch {
      // Ignore cleanup failures.
    }
    try {
      unlinkSync(this.accountLockPath(account));
    } catch {
      // Ignore cleanup failures.
    }
  }
}

export function isoNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "");
}

function cleanupStaleLock(lockPath: string): void {
  if (!existsSync(lockPath)) {
    return;
  }
  try {
    const payload = JSON.parse(readFileSync(lockPath, "utf8")) as { pid?: unknown; created_at?: unknown };
    const createdAt = typeof payload.created_at === "string" ? payload.created_at : "";
    const expired = createdAt ? Date.now() - Date.parse(`${createdAt}Z`) > lockTtlSeconds() * 1000 : false;
    const dead = typeof payload.pid === "number" && !pidAlive(payload.pid);
    if (expired || dead) {
      unlinkSync(lockPath);
    }
  } catch {
    // Leave unreadable locks alone.
  }
}

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function parseJsonOrNull(value: unknown): unknown {
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(String(value));
  } catch {
    return null;
  }
}

export function ensureParent(path: string): void {
  mkdirSync(dirname(path), { recursive: true });
}
