from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from calendar import timegm
from pathlib import Path
from typing import Any

from .pool import DreaminaPool
from .settings import download_dir, dreamina_command
from .dreamina_utils import (
    account_id_from_provider_user_id,
    extract_submit_id,
    find_video_url,
    normalize_dreamina_status,
    parse_json_payload,
    parse_login_output,
    provider_user_id_from_credit,
)


GENERATION_COMMANDS = {"text2video", "image2video", "frames2video"}


async def run_dreamina(args: list[str], home_dir: Path) -> dict[str, Any]:
    home_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home_dir)}
    process = await asyncio.create_subprocess_exec(
        dreamina_command(),
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    return {
        "code": process.returncode or 0,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
    }


class DreaminaService:
    def __init__(self, pool: DreaminaPool | None = None):
        self.pool = pool or DreaminaPool()

    def next_account_id(self) -> str:
        used = self.pool.used_login_account_ids()
        index = 1
        while True:
            account_id = f"account-{index:03d}"
            if account_id not in used:
                return account_id
            index += 1

    async def start_login(self) -> dict[str, Any]:
        self.pool.ensure()
        account_id = self.next_account_id()
        session_id = uuid.uuid4().hex
        home_dir = self.pool.accounts_dir / account_id
        if home_dir.exists():
            shutil.rmtree(home_dir)
        home_dir.mkdir(parents=True, exist_ok=True)
        result = await run_dreamina(["login", "--headless"], home_dir)
        if result["code"] != 0:
            detail = result["stderr"].strip() or result["stdout"].strip() or "dreamina login failed"
            raise RuntimeError(detail)
        parsed = parse_login_output(result["stdout"])
        session = self.pool.create_login_session(
            session_id=session_id,
            account_id=account_id,
            home_dir=home_dir,
            verification_uri=parsed["verification_uri"],
            user_code=parsed.get("user_code", ""),
            device_code=parsed["device_code"],
            expires_at=parsed.get("expires_at"),
            stdout=result["stdout"],
            stderr=result["stderr"],
        )
        return {
            **session,
            "next": f"Open {parsed['verification_uri']} and enter code {parsed.get('user_code', '')}, then run `ainong login check {session_id}`.",
        }

    async def check_login(self, session_id: str) -> dict[str, Any]:
        row = self.pool.login_session_internal(session_id)
        if not row:
            raise LookupError("登录会话不存在")
        if row["status"] == "succeeded":
            return self.pool.login_session(session_id) or {}
        if self._is_expired(row.get("expires_at")):
            self.pool.mark_login_session(session_id, "expired", error="登录授权已过期")
            return self.pool.login_session(session_id) or {}

        home_dir = Path(str(row["home_dir"]))
        result = await run_dreamina(
            ["login", "checklogin", f"--device_code={row['device_code']}", "--poll=1"],
            home_dir,
        )
        output = f"{result['stdout']}\n{result['stderr']}".strip()
        if result["code"] != 0:
            if "等待登录超时" in output or "timeout" in output.lower():
                self.pool.mark_login_session(
                    session_id,
                    "pending",
                    stdout=result["stdout"],
                    stderr=result["stderr"],
                )
                return self.pool.login_session(session_id) or {}
            self.pool.mark_login_session(
                session_id,
                "failed",
                error=output or "登录失败",
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            return self.pool.login_session(session_id) or {}

        credit = await self._read_credit(home_dir)
        provider_user_id = provider_user_id_from_credit(credit)
        final_account_id = account_id_from_provider_user_id(provider_user_id, str(row["account_id"]))
        existing_final_account = self.pool.account_row(final_account_id)
        if existing_final_account and final_account_id != row["account_id"]:
            self.pool.mark_login_session(
                session_id,
                "failed",
                provider_user_id=provider_user_id,
                account_id=str(existing_final_account["id"]),
                error=f"该 Dreamina 用户已在账号池中：{existing_final_account['id']}",
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            return self.pool.login_session(session_id) or {}

        duplicate = await self._find_duplicate_provider_user(provider_user_id, final_account_id)
        if duplicate and duplicate["id"] != final_account_id:
            self.pool.mark_login_session(
                session_id,
                "failed",
                provider_user_id=provider_user_id,
                account_id=str(duplicate["id"]),
                error=f"该 Dreamina 用户已在账号池中：{duplicate['id']}",
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            return self.pool.login_session(session_id) or {}

        account_home = self._promote_login_home(home_dir, str(row["account_id"]), final_account_id)
        account = self.pool.register_account(
            final_account_id,
            account_home,
            provider_user_id=provider_user_id or None,
            credit_snapshot=credit,
        )
        self.pool.mark_login_session(
            session_id,
            "succeeded",
            provider_user_id=provider_user_id,
            account_id=account.id,
            stdout=result["stdout"],
            stderr=result["stderr"],
        )
        return self.pool.login_session(session_id) or {}

    async def refresh_credit(self, account_id: str) -> dict[str, Any] | None:
        account = self.pool.account_row(account_id)
        if not account:
            return None
        credit = await self._read_credit(Path(str(account["home_dir"])))
        provider_user_id = provider_user_id_from_credit(credit)
        duplicate = await self._find_duplicate_provider_user(provider_user_id, account_id)
        last_error = None
        provider_user_id_to_store = provider_user_id or None
        if duplicate and duplicate["id"] != account_id:
            last_error = f"该 Dreamina 用户已在账号池中：{duplicate['id']}"
            credit = None
            provider_user_id_to_store = None
        self.pool.update_account_credit(
            account_id,
            provider_user_id=provider_user_id_to_store,
            credit_snapshot=credit,
            last_error=last_error,
            disable=bool(last_error),
        )
        return credit

    def update_account_status(self, account_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"active", "disabled"}:
            raise ValueError("status must be active or disabled")
        return self.pool.update_account_status(account_id, status)

    async def submit_task(self, command: str, args: list[str]) -> dict[str, Any]:
        if command not in GENERATION_COMMANDS:
            raise ValueError(f"Unsupported Dreamina command: {command}")
        accounts = self.pool.active_accounts()
        for account in accounts:
            fd = self.pool.try_lock_account(account)
            if fd is None:
                continue
            self.pool.mark_account_used(account.id)
            try:
                result = await run_dreamina([command, *args], account.home_dir)
                parsed = parse_json_payload(result["stdout"])
                provider_task_id = extract_submit_id(result["stdout"])
                task_id = provider_task_id or uuid.uuid4().hex
                status = "submitted" if result["code"] == 0 and provider_task_id else "failed"
                self.pool.upsert_task(
                    task_id=task_id,
                    account_id=account.id,
                    command=command,
                    args=args,
                    status=status,
                    stdout=result["stdout"],
                    stderr=result["stderr"],
                    provider_task_id=provider_task_id,
                    result_json=parsed,
                )
                if result["code"] != 0 or not provider_task_id:
                    self.pool.mark_account_error(account.id, result["stderr"] or result["stdout"])
                return {
                    "task_id": task_id,
                    "provider_task_id": provider_task_id,
                    "account_id": account.id,
                    "status": status,
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                }
            finally:
                self.pool.release_lock(account, fd)
        raise RuntimeError("No available active Dreamina account. Run `ainong login` first.")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task = self.pool.task(task_id)
        if not task:
            raise LookupError("Task not found")
        provider_task_id = task.get("provider_task_id")
        if not provider_task_id:
            return task

        account = self.pool.task_account(task_id)
        if not account:
            return task

        target_dir = download_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        result = await run_dreamina(
            ["query_result", f"--submit_id={provider_task_id}", f"--download_dir={target_dir}"],
            account.home_dir,
        )
        parsed = parse_json_payload(result["stdout"])
        if result["code"] != 0:
            return {
                **task,
                "query_error": result["stderr"].strip() or result["stdout"].strip(),
            }

        status = normalize_dreamina_status((parsed or {}).get("gen_status"))
        try:
            args = json_loads_list(str(task.get("args_json") or "[]"))
        except ValueError:
            args = []
        self.pool.upsert_task(
            task_id=task_id,
            account_id=account.id,
            command=str(task["command"]),
            args=args,
            status=status,
            stdout=result["stdout"],
            stderr=result["stderr"],
            provider_task_id=str(provider_task_id),
            result_json=parsed,
        )
        updated = self.pool.task(task_id) or task
        return {
            **updated,
            "video_url": find_video_url(parsed),
        }

    async def _read_credit(self, home_dir: Path) -> dict[str, Any] | None:
        result = await run_dreamina(["user_credit"], home_dir)
        return parse_json_payload(result["stdout"]) if result["code"] == 0 else None

    def _promote_login_home(self, home_dir: Path, account_id: str, final_account_id: str) -> Path:
        if final_account_id == account_id:
            return home_dir
        final_home_dir = self.pool.accounts_dir / final_account_id
        if final_home_dir.exists():
            return final_home_dir
        final_home_dir.parent.mkdir(parents=True, exist_ok=True)
        if home_dir.exists():
            shutil.move(str(home_dir), str(final_home_dir))
        else:
            final_home_dir.mkdir(parents=True, exist_ok=True)
        return final_home_dir

    async def _find_duplicate_provider_user(
        self,
        provider_user_id: str,
        current_account_id: str,
    ) -> dict[str, object] | None:
        duplicate = self.pool.account_by_provider_user_id(provider_user_id)
        if duplicate and duplicate["id"] != current_account_id:
            return duplicate
        if not provider_user_id:
            return None
        can_store_matching_unmarked_account = duplicate is None

        for account in self.pool.accounts_without_provider_user_id():
            if account["id"] == current_account_id:
                continue
            credit = await self._read_credit(Path(str(account["home_dir"])))
            discovered_provider_user_id = provider_user_id_from_credit(credit)
            if not discovered_provider_user_id:
                continue
            if discovered_provider_user_id == provider_user_id:
                if duplicate and duplicate["id"] == current_account_id:
                    self.pool.update_account_credit(
                        str(account["id"]),
                        provider_user_id=None,
                        credit_snapshot=None,
                        last_error=f"该 Dreamina 用户已在账号池中：{current_account_id}",
                        disable=True,
                    )
                    continue
                if can_store_matching_unmarked_account:
                    self.pool.update_account_credit(
                        str(account["id"]),
                        provider_user_id=discovered_provider_user_id,
                        credit_snapshot=credit,
                        last_error=None,
                    )
                    return self.pool.account_row(str(account["id"]))
                return account
            discovered_duplicate = self.pool.account_by_provider_user_id(discovered_provider_user_id)
            if discovered_duplicate and discovered_duplicate["id"] != account["id"]:
                continue
            self.pool.update_account_credit(
                str(account["id"]),
                provider_user_id=discovered_provider_user_id,
                credit_snapshot=credit,
                last_error=None,
            )
        return None

    def _is_expired(self, expires_at: object) -> bool:
        if not expires_at:
            return False
        try:
            expires = time.strptime(str(expires_at)[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return False
        return timegm(expires) < time.time()


def json_loads_list(value: str) -> list[str]:
    import json

    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("expected list")
    return [str(item) for item in parsed]
