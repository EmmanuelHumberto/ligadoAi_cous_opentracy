"""Local persistence for measurement sessions."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MeasurementLocalStore:
    """Persistência local de sessões de medição.

    Thread-safe para single-threaded (uso normal do Cous).
    NÃO suporta acesso concorrente por múltiplos processos.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: dict[str, list[dict[str, Any]]] | None = None
        self._dirty: bool = False

    def create_session(self, header: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        session = {
            "id": self._generate_id(),
            "status": "draft",
            "sync_status": "local_only",
            "header": deepcopy(header),
            "snapshots": [],
            "total_snapshots": 0,
            "valid_snapshots": 0,
            "invalid_snapshots": 0,
            "snapshots_by_type": {},
            "created_at": now,
            "updated_at": now,
        }
        data = self._load()
        data["sessions"].append(session)
        self._save(data)
        return deepcopy(session)

    def list_sessions(self) -> list[dict[str, Any]]:
        data = self._load()
        sessions = sorted(
            data["sessions"],
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return [self._without_snapshots(session) for session in sessions]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        data = self._load()
        for session in data["sessions"]:
            if str(session.get("id")) == session_id:
                return deepcopy(session)
        return None

    def resolve_session_id(self, value: str) -> str | None:
        target = value.strip()
        if not target:
            return None
        sessions = self.full_sessions()
        exact = [
            session
            for session in sessions
            if str(session.get("id")) == target or str(session.get("remote_id") or "") == target
        ]
        if exact:
            return str(exact[0].get("id"))
        prefix = [
            session
            for session in sessions
            if str(session.get("id") or "").startswith(target)
            or str(session.get("remote_id") or "").startswith(target)
        ]
        if len(prefix) == 1:
            return str(prefix[0].get("id"))
        return None

    def full_sessions(self) -> list[dict[str, Any]]:
        data = self._load()
        sessions = sorted(
            data["sessions"],
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return [deepcopy(session) for session in sessions]

    def replace_session(self, session: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        updated = deepcopy(session)
        updated["updated_at"] = utc_now_iso()
        for index, current in enumerate(data["sessions"]):
            if str(current.get("id")) == str(updated.get("id")):
                data["sessions"][index] = updated
                self._save(data)
                return deepcopy(updated)
        data["sessions"].append(updated)
        self._save(data)
        return deepcopy(updated)

    def delete_session(self, session_id: str) -> bool:
        data = self._load()
        remaining = [
            session for session in data["sessions"] if str(session.get("id")) != session_id
        ]
        deleted = len(remaining) != len(data["sessions"])
        if deleted:
            data["sessions"] = remaining
            self._save(data)
        return deleted

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._cache is not None:
            return self._cache
        if not self._path.is_file():
            self._cache = {"sessions": []}
        else:
            with self._path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            sessions = data.get("sessions", [])
            self._cache = {"sessions": sessions if isinstance(sessions, list) else []}
        return self._cache

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._cache = data
        self._dirty = True
        self._flush()

    def _flush(self) -> None:
        """Regrava no disco se houver alterações pendentes."""
        if not self._dirty or self._cache is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        dir_path = self._path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                json.dump(self._cache, tmp, ensure_ascii=True, indent=2, sort_keys=True)
                tmp.flush()
                os.fsync(tmp.fileno())
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
        os.replace(tmp_path, self._path)
        self._dirty = False

    def invalidate_cache(self) -> None:
        """Força releitura do disco na próxima operação. Útil para testes."""
        self._cache = None
        self._dirty = False

    def _generate_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("med_%Y%m%d_%H%M%S")
        return f"{stamp}_{uuid4().hex[:6]}"

    def _without_snapshots(self, session: dict[str, Any]) -> dict[str, Any]:
        copy = deepcopy(session)
        copy.pop("snapshots", None)
        return copy
