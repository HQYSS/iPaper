"""
Runtime metadata helpers.

These values make it obvious which code a long-running backend process is
actually serving.
"""
from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime
from typing import Optional

from config import PROJECT_ROOT, settings

STARTED_AT = datetime.now()


def _git_output(*args: str) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None


def get_runtime_info() -> dict:
    status = _git_output("status", "--short")
    return {
        "pid": os.getpid(),
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": int((datetime.now() - STARTED_AT).total_seconds()),
        "python_version": platform.python_version(),
        "project_root": str(PROJECT_ROOT),
        "sync_role": settings.sync_role,
        "llm_provider": settings.llm.provider,
        "git": {
            "sha": _git_output("rev-parse", "HEAD"),
            "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(status),
        },
    }
