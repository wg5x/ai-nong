from __future__ import annotations

import json
import re
from typing import Any


def parse_login_output(stdout: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in ("verification_uri", "user_code", "device_code", "poll_interval", "expires_at"):
        match = re.search(rf"^{key}:\s*(.+?)\s*$", stdout, re.MULTILINE)
        if match:
            fields[key] = match.group(1).strip()
    if not fields.get("verification_uri") or not fields.get("device_code"):
        raise ValueError("未能解析 dreamina 登录授权信息")
    return fields


def parse_json_payload(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    for candidate in reversed(_extract_json_candidates(text)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def provider_user_id_from_credit(credit: dict[str, Any] | None) -> str:
    if not credit:
        return ""
    for key in ("user_id", "uid", "userId"):
        value = credit.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    user = credit.get("user")
    if isinstance(user, dict):
        for key in ("id", "user_id", "uid"):
            value = user.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def account_id_from_provider_user_id(provider_user_id: str, fallback: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{3,64}", provider_user_id):
        return provider_user_id
    return fallback


def extract_submit_id(stdout: str) -> str | None:
    parsed = parse_json_payload(stdout)
    found = _find_submit_id(parsed)
    if found:
        return found
    for pattern in (
        r'"submit_id"\s*:\s*"([^"]+)"',
        r'"submitId"\s*:\s*"([^"]+)"',
        r"\bsubmit_id\b\s*[:=]\s*([A-Za-z0-9_-]+)",
        r"\bsubmitId\b\s*[:=]\s*([A-Za-z0-9_-]+)",
    ):
        match = re.search(pattern, stdout, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def normalize_dreamina_status(status: object) -> str:
    text = str(status or "").lower()
    if text in ("success", "succeeded"):
        return "succeeded"
    if text in ("fail", "failed"):
        return "failed"
    return "processing"


def find_video_url(parsed: dict[str, Any] | None) -> str | None:
    if not parsed:
        return None
    for container in (parsed.get("result_json"), parsed):
        if not isinstance(container, dict):
            continue
        videos = container.get("videos")
        if isinstance(videos, list) and videos:
            video = videos[0]
            if isinstance(video, dict):
                return video.get("url") or video.get("video_url") or video.get("path")
    value = parsed.get("video_url")
    return str(value) if value else None


def _find_submit_id(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("submit_id", "submitId"):
        item = value.get(key)
        if isinstance(item, str):
            return item
    for child in value.values():
        found = _find_submit_id(child)
        if found:
            return found
    return None


def _extract_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : index + 1])
                start = -1
    return candidates
