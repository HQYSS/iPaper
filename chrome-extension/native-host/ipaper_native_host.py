#!/usr/bin/env python3
"""
iPaper Chrome Native Messaging host.

This host intentionally exposes only a tiny action allowlist:
- healthcheck: check whether the local iPaper backend is ready
- start_ipaper: launch iPaper.app and wait for the backend to become ready
- open_ipaper: launch/focus iPaper.app and wait for the backend to become ready
"""
import json
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IPAPER_APP = PROJECT_ROOT / "iPaper.app"
BACKEND_HEALTH_URL = "http://127.0.0.1:3000/"


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        return None
    if len(raw_length) != 4:
        raise ValueError("Invalid native message length header")

    message_length = struct.unpack("<I", raw_length)[0]
    if message_length <= 0 or message_length > 1024 * 1024:
        raise ValueError("Invalid native message size")

    raw_message = sys.stdin.buffer.read(message_length)
    if len(raw_message) != message_length:
        raise ValueError("Incomplete native message body")

    return json.loads(raw_message.decode("utf-8"))


def write_message(payload):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def backend_ready(timeout_seconds=1.2):
    try:
        with urllib.request.urlopen(BACKEND_HEALTH_URL, timeout=timeout_seconds) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read().decode("utf-8"))
            return data.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def wait_for_backend(timeout_seconds=45):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if backend_ready():
            return True
        time.sleep(1)
    return False


def open_ipaper_app():
    if not IPAPER_APP.exists():
        return {"ok": False, "error": f"找不到 iPaper.app: {IPAPER_APP}"}

    subprocess.Popen(
        ["open", str(IPAPER_APP)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True}


def start_ipaper():
    if backend_ready():
        return {"ok": True, "already_running": True}

    opened = open_ipaper_app()
    if not opened.get("ok"):
        return opened

    if wait_for_backend():
        return {"ok": True, "started": True}

    return {"ok": False, "error": "已尝试启动 iPaper，但后端健康检查超时"}


def open_ipaper():
    opened = open_ipaper_app()
    if not opened.get("ok"):
        return opened

    if wait_for_backend():
        return {"ok": True, "opened": True}

    return {"ok": False, "error": "已尝试打开 iPaper，但后端健康检查超时"}


def handle_message(message):
    action = message.get("action")
    if action == "healthcheck":
        return {"ok": True, "backend_ready": backend_ready()}
    if action == "start_ipaper":
        return start_ipaper()
    if action == "open_ipaper":
        return open_ipaper()
    return {"ok": False, "error": f"不支持的动作: {action}"}


def main():
    try:
        message = read_message()
        if message is None:
            return
        write_message(handle_message(message))
    except Exception as exc:
        write_message({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
