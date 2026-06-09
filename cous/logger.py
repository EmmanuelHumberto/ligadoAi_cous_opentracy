"""JSONL event logger for terminal activity."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLogger:
    def __init__(self, path: Path) -> None:
        self._path = path

    def log(self, event: str, **payload: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": utc_now_iso(), "event": event}
        record.update(payload)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
