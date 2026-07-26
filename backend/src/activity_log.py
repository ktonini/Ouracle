"""Curated user-facing activity log (never includes OTP codes or raw debug dumps)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .paths import get_user_data_dir

ActivityLevel = Literal["info", "success", "warning", "error"]

LOG_FILE = "activity_log.jsonl"
MAX_ENTRIES = 200

_lock = threading.Lock()


def _log_path() -> Path:
    return Path(get_user_data_dir()) / LOG_FILE


def append_activity(
    message: str,
    *,
    level: ActivityLevel = "info",
    category: str = "sync",
) -> None:
    """Append one activity event. Never pass secrets or OTP values in ``message``."""
    text = (message or "").strip()
    if not text:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "category": category,
        "message": text,
    }
    path = _log_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim_locked(path)


def _trim_locked(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_ENTRIES:
        return
    kept = lines[-MAX_ENTRIES:]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def read_activity(limit: int = 100) -> list[dict[str, Any]]:
    """Return newest-first activity entries."""
    limit = max(1, min(int(limit), MAX_ENTRIES))
    path = _log_path()
    with _lock:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    entries: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        message = str(parsed.get("message", "")).strip()
        if not message:
            continue
        entries.append(
            {
                "ts": str(parsed.get("ts") or ""),
                "level": str(parsed.get("level") or "info"),
                "category": str(parsed.get("category") or "sync"),
                "message": message,
            }
        )
    entries.reverse()
    return entries[:limit]


def clear_activity() -> None:
    path = _log_path()
    with _lock:
        if path.exists():
            path.unlink()
