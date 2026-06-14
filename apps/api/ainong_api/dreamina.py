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

    async def start_login(self) -> dict[str, Any]:
        self.pool.ensure()
        session_id = uuid.uuid4().hex
        temp_home = self.pool.login_sessions_dir / session_id
        temp_home.mkdir(parents=True, exist_ok=True)
        result = await run_dreamina(["login", "--headless"], temp_home)
        if result["code"] != 0:
            detail = result["stderr"].strip() or result["stdout"].strip() or "dreamina login failed"
            raise RuntimeError(detail)
        parsed = parse_login_output(result["stdout"])
        session = self.pool.create_login_session(
            session_id=session_id,
            temp_home_dir=temp_home,
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

        temp_home = Path(str(row["temp_home_dir"]))
        result = await run_dreamina(
            ["login", "checklogin", f"--device_code={row['device_code']}", "--poll=1"],
            temp_home,
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

        credit = await self._read_credit(temp_home)
        provider_user_id = provider_user_id_from_credit(credit)
        if not provider_user_id:
            self.pool.mark_login_session(
                session_id,
                "failed",
                error="登录成功，但未能从 dreamina user_credit 读取 provider_user_id",
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            return self.pool.login_session(session_id) or {}

        duplicate = self.pool.account_by_provider_user_id(provider_user_id)
        if duplicate:
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

        account_home = self.pool.accounts_dir / provider_user_id
        if account_home.exists():
            self.pool.mark_login_session(
                session_id,
                "failed",
                provider_user_id=provider_user_id,
                error=f"账号目录已存在但未注册：{account_home}",
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            return self.pool.login_session(session_id) or {}

        account_home.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_home), str(account_home))
        account = self.pool.register_account(
            provider_user_id,
            account_home,
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
