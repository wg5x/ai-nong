from __future__ import annotations

import os
from pathlib import Path


def ainong_home() -> Path:
    return Path(os.environ.get("AINONG_HOME", "~/.ainong")).expanduser()


def dreamina_command() -> str:
    return os.environ.get("DREAMINA_COMMAND", "dreamina")


def download_dir() -> Path:
    return Path(os.environ.get("AINONG_DOWNLOAD_DIR", str(ainong_home() / "dreamina" / "downloads"))).expanduser()


def lock_ttl_seconds() -> int:
    return int(os.environ.get("AINONG_LOCK_TTL_SECONDS", "1800"))
