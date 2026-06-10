"""Mock clients for local/offline terminal runs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from cous.measurements.analysis import build_chat_context, build_markdown_report, build_recent_summary, filter_sessions
from cous.measurements.store import MeasurementLocalStore
from cous.measurements.validation import validate_header, validate_snapshots


class MockOpenTracyClient:
    def __init__(self, *, agent_id: str) -> None:
        self._agent_id = agent_id

    def health(self) -> dict[str, bool]:
        return {"backend": True, "runtime": True}

    def chat(
        self,
        request: str,
        *,
        history: list[dict[str, str]] | None = None,
        channel: str = "terminal",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if channel == "terminal_summary":
            recent = history[-4:] if history else []
            lines = [f"{item.get('role')}: {item.get('content')}" for item in recent]
            response = "Resumo mock:\n" + "\n".join(lines[-4:])
        else:
            response = (
                "Resposta mock do OpenTracy.\n"
                f"agente={self._agent_id}\n"
                f"canal={channel}\n"
                f"pedido={request[:400]}"
            )
        return {
            "response": response,
            "trace_id": f"mock_{uuid4().hex[:12]}",
            "success": True,
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": "mock.search"},
            {"name": "mock.measurements"},
        ]

    def get_verticals(self) -> tuple[str, ...]:
        return DEFAULT_VERTICALS

    def promote_to_golden(self, trace_id: str) -> dict[str, Any]:
        return {"status": "ok", "trace_id": trace_id}

    def close(self) -> None:
        return None


class MockKnowledgeClient:
    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []
        self._jobs: dict[str, dict[str, Any]] = {}

    def status(self) -> dict[str, Any]:
        chunk_count = sum(int(item.get("chunk_count", 0)) for item in self._documents)
        return {"status": "ready", "document_count": len(self._documents), "chunk_count": chunk_count}

    def validate(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        approved = bool(text.strip())
        return {
            "approved": approved,
            "char_count": len(text),
            "content_type": path.suffix.lower().lstrip(".") or "text",
            "errors": [] if approved else [{"code": "empty_document"}],
        }

    def index(self, path: Path) -> dict[str, Any]:
        job_id = f"job_{uuid4().hex[:8]}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        self._documents = [item for item in self._documents if item["id"] != path.name]
        self._documents.append(
            {
                "id": path.name,
                "name": path.name,
                "path": str(path),
                "chunk_count": max(1, len(text) // 500 or 1),
            }
        )
        self._jobs[job_id] = {"job_id": job_id, "status": "indexed", "stage": "done"}
        return {"job_id": job_id}

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._jobs.get(job_id, {"job_id": job_id, "status": "failed", "error": {"code": "job_not_found"}})

    def list_documents(self) -> list[dict[str, Any]]:
        return deepcopy(self._documents)

    def search(self, query: str) -> list[dict[str, Any]]:
        terms = [item.strip().lower() for item in query.split() if item.strip()]
        results: list[dict[str, Any]] = []
        for document in self._documents:
            haystack = " ".join(str(document.get(key) or "").lower() for key in ("id", "name", "path"))
            score = sum(1 for term in terms if term in haystack) or (1 if not terms else 0)
            if score:
                results.append({"document_id": document["id"], "title": document["name"], "score": score, "snippet": document["path"]})
        return results

    def delete_document(self, document_id: str) -> None:
        self._documents = [item for item in self._documents if item["id"] != document_id]

    def get_verticals(self) -> tuple[str, ...]:
        return DEFAULT_VERTICALS

    def promote_to_golden(self, trace_id: str) -> dict[str, Any]:
        return {"status": "ok", "trace_id": trace_id}

    def close(self) -> None:
        return None


class MockMeasurementsClient:
    def __init__(self, store: MeasurementLocalStore) -> None:
        self._store = store

    def create_session(self, header: dict[str, Any]) -> dict[str, Any]:
        errors = validate_header(header)
        if errors:
            raise ValueError("; ".join(errors))
        return self._store.create_session(header)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "backend": "mock",
            "database_configured": False,
            "auth_configured": False,
        }

    def list_sessions(self, query: str | None = None) -> list[dict[str, Any]]:
        sessions = self._store.list_sessions()
        return filter_sessions(sessions, query) if query and query.strip() else sessions

    def get_session(self, session_id: str) -> dict[str, Any]:
        resolved = self._store.resolve_session_id(session_id) or session_id
        session = self._store.get_session(resolved)
        if session is None:
            raise ValueError(f"Sessao nao encontrada: {session_id}")
        return session

    def latest_session(self) -> dict[str, Any] | None:
        sessions = self._store.full_sessions()
        return sessions[0] if sessions else None

    def add_snapshots(self, session_id: str, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        session = self.get_session(session_id)
        valid, rejected = validate_snapshots(snapshots, allowed_types=set(session.get("header", {}).get("verticais") or []))
        current = deepcopy(session.get("snapshots") or [])
        current.extend(valid)
        session["snapshots"] = current
        session["status"] = "saved" if valid else session.get("status") or "draft"
        session["valid_snapshots"] = len(current)
        session["invalid_snapshots"] = int(session.get("invalid_snapshots") or 0) + len(rejected)
        session["total_snapshots"] = session["valid_snapshots"] + session["invalid_snapshots"]
        updated = self._store.replace_session(session)
        return {"accepted": len(valid), "rejected": len(rejected), "rejected_items": rejected, "session": updated}

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
        session["sync_status"] = "mock_synced"
        session["remote_id"] = str(session.get("remote_id") or uuid4())
        session["last_sync_error"] = ""
        return self._store.replace_session(session)

    def sync_pending_sessions(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        synced: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        candidates = [
            s for s in self._store.full_sessions()
            if str(s.get("status") or "") in {"saved", "diagnosed", "reported"}
            and str(s.get("sync_status") or "") != "synced"
        ]
        for idx, session in enumerate(candidates):
            session_id = str(session.get("id"))
            if on_progress is not None:
                on_progress(idx, len(candidates), f"Sincronizando {session_id[:12]}...")
            try:
                synced.append(self.sync_session(session_id))
            except Exception as exc:
                failed.append({"session_id": session_id, "error": str(exc)})
        return {
            "synced": synced,
            "failed": failed,
            "synced_count": len(synced),
            "failed_count": len(failed),
        }
    def diagnose(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        diagnostic = {
            "approved": bool(session.get("valid_snapshots")) and not bool(session.get("invalid_snapshots")),
            "summary": "Diagnostico mock baseado na coleta local.",
            "total_snapshots": int(session.get("total_snapshots") or 0),
            "valid_snapshots": int(session.get("valid_snapshots") or 0),
            "invalid_snapshots": int(session.get("invalid_snapshots") or 0),
            "header": deepcopy(session.get("header") or {}),
        }
        session["diagnostic"] = diagnostic
        session["status"] = "diagnosed"
        updated = self._store.replace_session(session)
        return {"session": updated, "diagnostic": diagnostic, "source": "mock"}

    def report(self, session_id: str) -> dict[str, Any]:
        diagnosed = self.diagnose(session_id)
        session = self.get_session(session_id)
        markdown = build_markdown_report(session)
        session["report_markdown"] = markdown
        session["status"] = "reported"
        updated = self._store.replace_session(session)
        return {"markdown": markdown, "session": updated, "source": "mock"}

    def get_verticals(self) -> tuple[str, ...]:
        return DEFAULT_VERTICALS

    def promote_to_golden(self, trace_id: str) -> dict[str, Any]:
        return {"status": "ok", "trace_id": trace_id}

    def close(self) -> None:
        return None


class MockFeedbackStore:
    """Mock para FeedbackStore — registros em memória."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> Any:
        from uuid import uuid4
        rec: dict[str, Any] = {"id": f"fb_{uuid4().hex[:8]}", **kwargs}
        self._records.append(rec)
        return rec

    def list_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._records)

    def export_as_goldens(self, output_path: Path) -> int:
        return len(self._records)
