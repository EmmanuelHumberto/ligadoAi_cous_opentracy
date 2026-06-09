"""JSONL event logger for terminal activity."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLogger:
    def __init__(
        self,
        path: Path,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._backup_count = backup_count

    def log(self, event: str, **payload: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_if_needed()
        record = {"ts": utc_now_iso(), "event": event}
        record.update(payload)
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
        except OSError as exc:
            # Log nunca deve derrubar a aplicação
            import sys
            print(f"[cous] Aviso: falha ao gravar log: {exc}", file=sys.stderr)

    def _rotate_if_needed(self) -> None:
        if not self._path.is_file():
            return
        if self._path.stat().st_size < self._max_bytes:
            return

        # Remove o backup mais antigo
        oldest = Path(str(self._path) + f".{self._backup_count}")
        oldest.unlink(missing_ok=True)

        # Rotaciona: N-1 → N, N-2 → N-1, ..., 1 → 2 (atômico)
        for i in range(self._backup_count - 1, 0, -1):
            src = Path(str(self._path) + f".{i}")
            dst = Path(str(self._path) + f".{i + 1}")
            if src.is_file():
                os.replace(src, dst)

        # Move o arquivo atual para .1 (atômico)
        os.replace(self._path, Path(str(self._path) + ".1"))
