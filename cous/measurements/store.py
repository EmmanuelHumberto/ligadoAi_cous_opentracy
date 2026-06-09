"""Local persistence for measurement sessions."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MeasurementLocalStore:
    def __init__(self, path: Path) -> None:
        self._path = path

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
        if not self._path.is_file():
            return {"sessions": []}
        with self._path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        sessions = data.get("sessions", [])
        return {"sessions": sessions if isinstance(sessions, list) else []}

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, indent=2, sort_keys=True)

    def _generate_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("med_%Y%m%d_%H%M%S")
        return f"{stamp}_{uuid4().hex[:6]}"

    def _without_snapshots(self, session: dict[str, Any]) -> dict[str, Any]:
        copy = deepcopy(session)
        copy.pop("snapshots", None)
        return copy
