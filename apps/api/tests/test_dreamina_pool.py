from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainong_api.dreamina import DreaminaService
from ainong_api.pool import DreaminaPool


def write_fake_dreamina(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  login)
    if [[ "${2:-}" == "--headless" ]]; then
      echo "verification_uri: https://jimeng.example/cli-auth"
      echo "user_code: user-code-123"
      echo "device_code: device-code-secret"
      echo "poll_interval: 1s"
      echo "expires_at: 2099-06-05T13:55:56Z"
      exit 0
    fi
    if [[ "${2:-}" == "checklogin" ]]; then
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
          download_dir="${1#--download_dir=}"; shift ;;
        --submit_id=*)
          submit_id="${1#--submit_id=}"; shift ;;
        --download_dir)
          download_dir="$2"; shift 2 ;;
        --submit_id)
          submit_id="$2"; shift 2 ;;
        *)
          shift ;;
      esac
    done
    mkdir -p "$download_dir"
    video_path="$download_dir/${submit_id}.mp4"
    printf 'fake mp4' > "$video_path"
    printf '{"submit_id":"%s","gen_status":"success","result_json":{"videos":[{"path":"%s"}]}}\\n' "$submit_id" "$video_path"
    exit 0
    ;;
esac
echo "unsupported $*" >&2
exit 2
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.anyio
async def test_login_session_promotes_provider_user_id(monkeypatch, tmp_path):
    fake_dreamina = tmp_path / "dreamina"
    write_fake_dreamina(fake_dreamina)
    monkeypatch.setenv("DREAMINA_COMMAND", str(fake_dreamina))

    pool = DreaminaPool(tmp_path / "pool")
    service = DreaminaService(pool)
    session = await service.start_login()

    assert session["account_id"] == "account-001"
    assert session["verification_uri"] == "https://jimeng.example/cli-auth"
    assert session["user_code"] == "user-code-123"
    assert session["status"] == "pending"
    assert "device_code" not in session

    checked = await service.check_login(str(session["id"]))
    assert checked["status"] == "succeeded"
    assert checked["account_id"] == "98321338731792"

    accounts = pool.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["id"] == "98321338731792"
    assert accounts[0]["status"] == "active"
    assert accounts[0]["provider_user_id"] == "98321338731792"
    assert accounts[0]["credit"]["total_credit"] == 6201
    assert (tmp_path / "pool" / "accounts" / "98321338731792").exists()


@pytest.mark.anyio
async def test_rejects_duplicate_provider_user(monkeypatch, tmp_path):
    fake_dreamina = tmp_path / "dreamina"
    write_fake_dreamina(fake_dreamina)
    monkeypatch.setenv("DREAMINA_COMMAND", str(fake_dreamina))

    pool = DreaminaPool(tmp_path / "pool")
    service = DreaminaService(pool)
    first = await service.start_login()
    assert (await service.check_login(str(first["id"])))["status"] == "succeeded"

    second = await service.start_login()
    second_checked = await service.check_login(str(second["id"]))

    assert second_checked["status"] == "failed"
    assert "98321338731792" in str(second_checked["last_error"])
    accounts = pool.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["id"] == "98321338731792"


@pytest.mark.anyio
async def test_submits_and_queries_with_original_account(monkeypatch, tmp_path):
    fake_dreamina = tmp_path / "dreamina"
    write_fake_dreamina(fake_dreamina)
    monkeypatch.setenv("DREAMINA_COMMAND", str(fake_dreamina))
    monkeypatch.setenv("AINONG_DOWNLOAD_DIR", str(tmp_path / "downloads"))

    pool = DreaminaPool(tmp_path / "pool")
    account_home = tmp_path / "pool" / "accounts" / "98321338731792"
    account_home.mkdir(parents=True)
    pool.ensure()
    with sqlite3.connect(pool.db_path) as db:
        db.execute(
            """
            INSERT INTO accounts (
              id, provider_user_id, home_dir, status, created_at, updated_at
            ) VALUES ('98321338731792', '98321338731792', ?, 'active', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """,
            (str(account_home),),
        )

    service = DreaminaService(pool)
    submitted = await service.submit_task("text2video", ["--prompt", "test prompt"])
    assert submitted["task_id"] == "submit-cli-123"
    assert submitted["account_id"] == "98321338731792"

    status = await service.get_task("submit-cli-123")
    assert status["status"] == "succeeded"
    assert str(status["video_url"]).endswith("submit-cli-123.mp4")
    assert (tmp_path / "downloads" / "submit-cli-123.mp4").exists()
