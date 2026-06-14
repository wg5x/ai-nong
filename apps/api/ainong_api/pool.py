from __future__ import annotations

import json
import os
import sqlite3
import time
from calendar import timegm
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .settings import ainong_home, lock_ttl_seconds


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


@dataclass(frozen=True)
class Account:
    id: str
    provider_user_id: str | None
    home_dir: Path
    status: str
    last_used_at: str | None


class DreaminaPool:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or ainong_home() / "dreamina"
        self.accounts_dir = self.base_dir / "accounts"
        self.login_sessions_dir = self.base_dir / "login_sessions"
        self.db_path = self.base_dir / "pool.db"

    def ensure(self) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self.login_sessions_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
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
                """
            )
            self._ensure_column(db, "login_sessions", "account_id", "TEXT")
            self._ensure_column(db, "login_sessions", "home_dir", "TEXT")
            self._ensure_column(db, "login_sessions", "stdout", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "login_sessions", "stderr", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "login_sessions", "last_error", "TEXT")
            login_columns = self._columns(db, "login_sessions")
            if "temp_home_dir" in login_columns:
                db.execute(
                    """
                    UPDATE login_sessions
                    SET home_dir = COALESCE(home_dir, temp_home_dir)
                    WHERE home_dir IS NULL AND temp_home_dir IS NOT NULL
                    """
                )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_dreamina_accounts_provider_user_id
                ON accounts(provider_user_id)
                WHERE provider_user_id IS NOT NULL AND provider_user_id <> ''
                """
            )

    def _ensure_column(self, db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = self._columns(db, table)
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _columns(self, db: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout = 5000")
            yield db
            db.commit()
        finally:
            db.close()

    def list_accounts(self) -> list[dict[str, object]]:
        self.ensure()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT id, provider_user_id, display_name, home_dir, status,
                       last_used_at, last_alive_at, credit_snapshot_json,
                       last_error, created_at, updated_at
                FROM accounts
                ORDER BY COALESCE(last_used_at, ''), id
                """
            ).fetchall()
        accounts = []
        for row in rows:
            item = dict(row)
            credit_json = item.pop("credit_snapshot_json", None)
            try:
                item["credit"] = json.loads(str(credit_json)) if credit_json else None
            except json.JSONDecodeError:
                item["credit"] = None
            accounts.append(item)
        return accounts

    def create_login_session(
        self,
        *,
        session_id: str,
        account_id: str,
        home_dir: Path,
        verification_uri: str,
        user_code: str,
        device_code: str,
        expires_at: str | None,
        stdout: str,
        stderr: str,
    ) -> dict[str, object]:
        self.ensure()
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO login_sessions (
                  id, account_id, home_dir, status, verification_uri, user_code,
                  device_code, expires_at, stdout, stderr, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    account_id,
                    str(home_dir),
                    verification_uri,
                    user_code,
                    device_code,
                    expires_at,
                    stdout,
                    stderr,
                    now,
                    now,
                ),
            )
        session = self.login_session(session_id)
        return session or {}

    def login_session(self, session_id: str) -> dict[str, object] | None:
        self.ensure()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT id, account_id, home_dir, provider_user_id, status,
                       verification_uri, user_code, expires_at, last_error,
                       created_at, updated_at
                FROM login_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def login_session_internal(self, session_id: str) -> dict[str, object] | None:
        self.ensure()
        with self.connect() as db:
            row = db.execute("SELECT * FROM login_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def used_login_account_ids(self) -> set[str]:
        self.ensure()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT id FROM accounts
                UNION
                SELECT account_id AS id
                FROM login_sessions
                WHERE status IN ('pending', 'succeeded')
                ORDER BY id
                """
            ).fetchall()
        return {str(row["id"]) for row in rows if row["id"]}

    def mark_login_session(
        self,
        session_id: str,
        status: str,
        *,
        provider_user_id: str | None = None,
        account_id: str | None = None,
        error: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                UPDATE login_sessions
                SET status = ?,
                    provider_user_id = COALESCE(?, provider_user_id),
                    account_id = COALESCE(?, account_id),
                    stdout = COALESCE(?, stdout),
                    stderr = COALESCE(?, stderr),
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, provider_user_id, account_id, stdout, stderr, error, now, session_id),
            )

    def active_accounts(self) -> list[Account]:
        self.ensure()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT id, provider_user_id, home_dir, status, last_used_at
                FROM accounts
                WHERE status = 'active'
                ORDER BY COALESCE(last_used_at, ''), id
                """
            ).fetchall()
        return [
            Account(
                id=row["id"],
                provider_user_id=row["provider_user_id"],
                home_dir=Path(row["home_dir"]),
                status=row["status"],
                last_used_at=row["last_used_at"],
            )
            for row in rows
        ]

    def upsert_task(
        self,
        *,
        task_id: str,
        account_id: str,
        command: str,
        args: list[str],
        status: str,
        stdout: str = "",
        stderr: str = "",
        provider_task_id: str | None = None,
        result_json: dict[str, object] | None = None,
    ) -> None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO tasks (
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
                  updated_at = excluded.updated_at
                """,
                (
                    task_id,
                    provider_task_id,
                    account_id,
                    command,
                    json.dumps(args, ensure_ascii=False),
                    status,
                    stdout,
                    stderr,
                    json.dumps(result_json, ensure_ascii=False) if result_json else None,
                    now,
                    now,
                ),
            )

    def task(self, task_id: str) -> dict[str, object] | None:
        self.ensure()
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def task_account(self, task_id: str) -> Account | None:
        self.ensure()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT a.id, a.provider_user_id, a.home_dir, a.status, a.last_used_at
                FROM tasks t
                JOIN accounts a ON a.id = t.account_id
                WHERE t.id = ?
                """,
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return Account(
            id=row["id"],
            provider_user_id=row["provider_user_id"],
            home_dir=Path(row["home_dir"]),
            status=row["status"],
            last_used_at=row["last_used_at"],
        )

    def mark_account_used(self, account_id: str) -> None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                "UPDATE accounts SET last_used_at = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                (now, now, account_id),
            )

    def mark_account_error(self, account_id: str, error: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE accounts SET last_error = ?, updated_at = ? WHERE id = ?",
                (error, iso_now(), account_id),
            )

    def account_by_provider_user_id(self, provider_user_id: str) -> dict[str, object] | None:
        if not provider_user_id:
            return None
        self.ensure()
        with self.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE provider_user_id = ?", (provider_user_id,)).fetchone()
        return dict(row) if row else None

    def account_row(self, account_id: str) -> dict[str, object] | None:
        self.ensure()
        with self.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None

    def accounts_without_provider_user_id(self) -> list[dict[str, object]]:
        self.ensure()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM accounts
                WHERE provider_user_id IS NULL OR provider_user_id = ''
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def register_account(
        self,
        account_id: str,
        home_dir: Path,
        provider_user_id: str | None = None,
        display_name: str | None = None,
        credit_snapshot: dict[str, object] | None = None,
    ) -> Account:
        self.ensure()
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO accounts (
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
                  updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    provider_user_id,
                    display_name,
                    str(home_dir),
                    now,
                    json.dumps(credit_snapshot, ensure_ascii=False) if credit_snapshot else None,
                    now,
                    now,
                ),
            )
        return Account(account_id, provider_user_id, home_dir, "active", None)

    def update_account_credit(
        self,
        account_id: str,
        *,
        provider_user_id: str | None,
        credit_snapshot: dict[str, object] | None,
        last_error: str | None,
        disable: bool = False,
    ) -> None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                UPDATE accounts
                SET last_alive_at = CASE WHEN ? THEN ? ELSE last_alive_at END,
                    status = CASE WHEN ? THEN 'disabled' ELSE status END,
                    provider_user_id = COALESCE(?, provider_user_id),
                    credit_snapshot_json = COALESCE(?, credit_snapshot_json),
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    last_error is None,
                    now,
                    disable,
                    provider_user_id,
                    json.dumps(credit_snapshot, ensure_ascii=False) if credit_snapshot else None,
                    last_error,
                    now,
                    account_id,
                ),
            )

    def update_account_status(self, account_id: str, status: str) -> dict[str, object] | None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, account_id),
            )
        return self.account_row(account_id)

    def account_lock_path(self, account: Account) -> Path:
        return account.home_dir / ".ainong.lock"

    def try_lock_account(self, account: Account) -> int | None:
        account.home_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.account_lock_path(account)
        for _ in range(2):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                cleanup_stale_lock(lock_path)
        else:
            return None
        os.write(
            fd,
            json.dumps(
                {
                    "pid": os.getpid(),
                    "provider_user_id": account.provider_user_id,
                    "created_at": iso_now(),
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        return fd

    def release_lock(self, account: Account, fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            self.account_lock_path(account).unlink()
        except OSError:
            pass


def cleanup_stale_lock(lock_path: Path) -> None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    created_at = payload.get("created_at")
    expired = False
    if isinstance(created_at, str):
        try:
            created = time.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S")
            expired = time.time() - timegm(created) > lock_ttl_seconds()
        except ValueError:
            expired = False
    pid = payload.get("pid")
    dead = isinstance(pid, int) and not pid_alive(pid)
    if expired or dead:
        try:
            lock_path.unlink()
        except OSError:
            pass


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
