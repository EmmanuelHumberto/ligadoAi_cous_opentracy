"""Client for OpenTracy measurements endpoints."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from cous.auth import TokenProvider
from cous.clients.base import AuthenticatedHttpClient
from cous.config import OpenTracyConfig
from cous.measurements.analysis import (
    build_chat_context,
    build_markdown_report,
    build_recent_summary,
    filter_sessions,
)
from cous.measurements.constants import DEFAULT_VERTICALS
from cous.measurements.serial_capture import normalize_snapshot_type, normalize_verticals
from cous.measurements.store import MeasurementLocalStore
from cous.measurements.validation import validate_header, validate_snapshots


class MeasurementsClient:
    def __init__(
        self,
        config: OpenTracyConfig,
        token_provider: TokenProvider,
        store: MeasurementLocalStore,
    ) -> None:
        self._http = AuthenticatedHttpClient(
            token_provider=token_provider,
            timeout=config.timeout,
        )
        self._runtime_url = config.runtime_url.rstrip("/")
        self._store = store

    def create_session(self, header: dict[str, Any]) -> dict[str, Any]:
        errors = validate_header(header)
        if errors:
            raise ValueError("; ".join(errors))
        return self._store.create_session(header)

    def status(self) -> dict[str, Any]:
        return self._http.get(f"{self._runtime_url}/measurements/status")

    def list_sessions(self, query: str | None = None) -> list[dict[str, Any]]:
        sessions = self._store.list_sessions()
        if query and query.strip():
            return filter_sessions(sessions, query)
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any]:
        resolved = self._store.resolve_session_id(session_id) or session_id
        session = self._store.get_session(resolved)
        if session is None:
            raise ValueError(f"Sessao nao encontrada: {session_id}")
        return session

    def latest_session(self) -> dict[str, Any] | None:
        sessions = self._store.full_sessions()
        return sessions[0] if sessions else None

    def add_snapshots(
        self,
        session_id: str,
        snapshots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        allowed_types = normalize_verticals(session.get("header", {}).get("verticais") or DEFAULT_VERTICALS)
        valid, rejected = validate_snapshots(snapshots, allowed_types=allowed_types)
        current = deepcopy(session.get("snapshots") or [])
        current.extend(valid)
        session["snapshots"] = current
        session["status"] = "saved" if valid else session.get("status") or "draft"
        session["valid_snapshots"] = len(current)
        session["invalid_snapshots"] = int(session.get("invalid_snapshots") or 0) + len(rejected)
        session["total_snapshots"] = session["valid_snapshots"] + session["invalid_snapshots"]
        counts: dict[str, int] = {}
        for snapshot in current:
            snapshot_type = normalize_snapshot_type(snapshot.get("type"))
            counts[snapshot_type] = counts.get(snapshot_type, 0) + 1
        session["snapshots_by_type"] = counts
        updated = self._store.replace_session(session)
        return {
            "accepted": len(valid),
            "rejected": len(rejected),
            "rejected_items": rejected,
            "session": updated,
        }

    def save_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        session["status"] = "saved"
        return self._store.replace_session(session)

    def abandon_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        session["status"] = "abandoned"
        return self._store.replace_session(session)

    def delete_session(self, session_id: str) -> bool:
        return self._store.delete_session(session_id)

    def chat_context(self, query: str) -> str:
        return build_chat_context(query, self._store.full_sessions())

    def recent_summary(self) -> str:
        return build_recent_summary(self._store.full_sessions())

    def sync_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        header = deepcopy(session.get("header") or {})
        remote_id = str(session.get("remote_id") or "")
        try:
            if remote_id:
                remote_session = self._http.get(
                    f"{self._runtime_url}/measurements/sessions/{remote_id}"
                )
            else:
                remote_session = self._http.post(
                    f"{self._runtime_url}/measurements/sessions",
                    {"header": header},
                )
                remote_id = str(remote_session.get("id") or "")
            snapshots = deepcopy(session.get("snapshots") or [])
            if snapshots:
                self._http.post(
                    f"{self._runtime_url}/measurements/sessions/{remote_id}/snapshots",
                    {"snapshots": snapshots},
                )
            session["remote_id"] = remote_id
            session["sync_status"] = "synced"
            session["last_sync_error"] = ""
            return self._store.replace_session(session)
        except Exception as exc:
            session["sync_status"] = "sync_failed"
            session["last_sync_error"] = str(exc)
            self._store.replace_session(session)
            raise

    def sync_pending_sessions(self) -> list[dict[str, Any]]:
        synced: list[dict[str, Any]] = []
        for session in self._store.full_sessions():
            if str(session.get("status") or "") not in {"saved", "diagnosed", "reported"}:
                continue
            if str(session.get("sync_status") or "") == "synced":
                continue
            synced.append(self.sync_session(str(session.get("id"))))
        return synced

    def diagnose(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        remote_id = str(session.get("remote_id") or "")
        if not remote_id:
            try:
                session = self.sync_session(session_id)
                remote_id = str(session.get("remote_id") or "")
            except Exception:
                return self._diagnose_local(session_id)
        try:
            result = self._http.post(
                f"{self._runtime_url}/measurements/sessions/{remote_id}/diagnose",
                {},
            )
        except Exception:
            return self._diagnose_local(session_id)
        updated = self._merge_remote_session(session_id, result.get("session") or {})
        return {
            "session": updated,
            "diagnostic": result.get("diagnostic") or updated.get("diagnostic") or {},
            "source": "remote",
        }

    def report(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        remote_id = str(session.get("remote_id") or "")
        if not remote_id:
            try:
                session = self.sync_session(session_id)
                remote_id = str(session.get("remote_id") or "")
            except Exception:
                return self._report_local(session_id)
        try:
            result = self._http.post(
                f"{self._runtime_url}/measurements/sessions/{remote_id}/report",
                {},
            )
        except Exception:
            return self._report_local(session_id)
        updated = self._merge_remote_session(session_id, result.get("session") or {})
        markdown = str(result.get("markdown") or updated.get("report_markdown") or "")
        return {"markdown": markdown, "session": updated, "source": "remote"}

    def _diagnose_local(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        diagnostic = {
            "approved": bool(session.get("valid_snapshots")) and not bool(session.get("invalid_snapshots")),
            "summary": (
                "Coleta valida para analise tecnica inicial."
                if session.get("valid_snapshots")
                else "Nenhum snapshot valido foi coletado."
            ),
            "total_snapshots": int(session.get("total_snapshots") or 0),
            "valid_snapshots": int(session.get("valid_snapshots") or 0),
            "invalid_snapshots": int(session.get("invalid_snapshots") or 0),
            "header": deepcopy(session.get("header") or {}),
            "type_counts": deepcopy(session.get("snapshots_by_type") or {}),
        }
        session["diagnostic"] = diagnostic
        session["status"] = "diagnosed"
        updated = self._store.replace_session(session)
        return {"session": updated, "diagnostic": diagnostic, "source": "local"}

    def _report_local(self, session_id: str) -> dict[str, Any]:
        diagnosed = self._diagnose_local(session_id)
        session = self.get_session(session_id)
        markdown = build_markdown_report(session)
        session["report_markdown"] = markdown
        session["status"] = "reported"
        updated = self._store.replace_session(session)
        return {"markdown": markdown, "session": updated, "source": "local"}

    def _merge_remote_session(self, local_session_id: str, remote_session: dict[str, Any]) -> dict[str, Any]:
        session = self.get_session(local_session_id)
        if remote_session:
            session["remote_id"] = str(remote_session.get("id") or session.get("remote_id") or "")
            session["status"] = str(remote_session.get("status") or session.get("status") or "saved")
            session["total_snapshots"] = int(remote_session.get("total_snapshots") or session.get("total_snapshots") or 0)
            session["valid_snapshots"] = int(remote_session.get("valid_snapshots") or session.get("valid_snapshots") or 0)
            session["invalid_snapshots"] = int(remote_session.get("invalid_snapshots") or session.get("invalid_snapshots") or 0)
            session["diagnostic"] = remote_session.get("diagnostic") or session.get("diagnostic")
            session["report_markdown"] = remote_session.get("report_markdown") or session.get("report_markdown")
        session["sync_status"] = "synced"
        session["last_sync_error"] = ""
        return self._store.replace_session(session)

    def close(self) -> None:
        self._http.close()
