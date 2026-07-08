"""Client for OpenTracy measurements endpoints."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

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
        self._config = config
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
        allowed_types = normalize_verticals(
            session.get("header", {}).get("verticais") or DEFAULT_VERTICALS
        )
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

    def delete_remote_session(self, session_id: str) -> None:
        self._http.delete(f"{self._runtime_url}/measurements/sessions/{session_id}")

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

    def sync_pending_sessions(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Sincroniza todas as sessões pendentes. Coleta falhas sem abortar o lote.

        Args:
            on_progress: Callback opcional (current, total, description).
                         None = sem reporte de progresso.

        Returns:
            dict com synced (list), failed (list), synced_count, failed_count.

        BREAKING (interno): O retorno mudou de list[dict] para dict com sumário.
        Apenas _sync_measurements() consome este método.
        """
        candidates = [
            session for session in self._store.full_sessions()
            if str(session.get("status") or "") in {"saved", "diagnosed", "reported"}
            and str(session.get("sync_status") or "") != "synced"
        ]

        synced: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        total = len(candidates)

        for idx, session in enumerate(candidates):
            session_id = str(session.get("id"))
            if on_progress is not None:
                on_progress(idx, total, f"Sincronizando {session_id[:12]}...")
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

    def diagnose_v3(self, session_id: str) -> dict[str, Any]:
        """Envia medição para diagnóstico COUS v3.1 (Knowledge Graph + Confiança Formal).

        Monta o payload DiagnosisRequestPayload a partir da sessão local,
        enfileira no OpenTracy e retorna o correlation_id para polling.
        """
        from datetime import UTC, datetime
        from uuid import uuid4

        from cous.contracts.v3_schemas import (
            DiagnosisContextSchema,
            DiagnosisRequestPayload,
            EvidenceItemSchema,
        )
        session = self.get_session(session_id)
        header = session.get("header") or {}
        snapshots = session.get("snapshots") or []

        # Montar evidence_set a partir dos snapshots
        # Agrupar por tipo e extrair métricas relevantes
        evidence_items: list[EvidenceItemSchema] = []
        snap_by_type: dict[str, list[dict]] = {}
        for snap in snapshots:
            t = snap.get("type", "unknown")
            snap_by_type.setdefault(t, []).append(snap)

        for snap_type, snaps in snap_by_type.items():
            evidence = EvidenceItemSchema(
                evidence_id=uuid4(),
                evidence_type="physical",
                evidence_strength="moderate" if len(snaps) > 50 else "weak",
                source_reference=f"capture:{session_id}:{snap_type}",
                confidence=min(len(snaps) / 200.0, 1.0),
                data=self._build_evidence_data(snap_type, snaps),
            )
            evidence_items.append(evidence)

        correlation_id = uuid4()
        ids, missing_ids = self._resolve_diagnosis_ids(session)
        if missing_ids and self._config.diagnosis_auto_resolve_identity:
            try:
                session = self._resolve_remote_capture_identity(session)
                ids, missing_ids = self._resolve_diagnosis_ids(session)
            except Exception as exc:
                session["diagnosis_v3_identity_error"] = str(exc)

        if missing_ids:
            result = {
                "status": "local_fallback",
                "error": (
                    "Diagnostico v3 requer IDs reais: "
                    + ", ".join(missing_ids)
                ),
            }
            session["diagnosis_correlation_id"] = str(correlation_id)
            session["diagnosis_status"] = result["status"]
            session["diagnosis_v3_error"] = result["error"]
            updated = self._store.replace_session(session)
            return {
                "session": updated,
                "diagnostic": {
                    "correlation_id": str(correlation_id),
                    "status": result["status"],
                    "error": result["error"],
                    "evidence_count": len(evidence_items),
                    "snapshot_types": list(snap_by_type.keys()),
                    "snapshot_count": len(snapshots),
                },
                "source": "v3-not-enqueued",
            }

        payload = DiagnosisRequestPayload(
            correlation_id=correlation_id,
            capture_session_id=ids["capture_session_id"],
            instance_id=ids["instance_id"],
            domain_id=ids["domain_id"],
            queued_at=datetime.now(UTC),
            callback_endpoint=self._config.diagnosis_callback_endpoint,
            evidence_set=evidence_items,
            context=DiagnosisContextSchema(
                reported_problem=header.get("observacoes"),
                instance_history_summary=(
                    f"{header.get('fabricante','?')} {header.get('modelo','?')} "
                    f"— {len(snapshots)} snapshots"
                ),
            ),
        )

        # Enviar para o OpenTracy (se disponível)
        try:
            from cous.clients.diagnosis import DiagnosisClient
            diag = DiagnosisClient(self._config, self._http._token_provider)
            result = diag.request_diagnosis(payload)
            source = "v3-remote"
        except Exception as e:
            result = {"status": "local_fallback", "error": str(e)}
            source = "v3-not-enqueued"

        # Armazenar correlation_id na sessão
        session["diagnosis_correlation_id"] = str(correlation_id)
        session["diagnosis_status"] = result.get("status", "unknown")
        session["diagnosis_v3_payload"] = payload.model_dump(mode="json")
        session.pop("diagnosis_result", None)
        session.pop("diagnosis_completed_at", None)
        session.pop("diagnosis_attempts", None)
        session.pop("diagnosis_last_attempt_at", None)
        session.pop("diagnosis_queue_status", None)
        if source == "v3-remote":
            session.pop("diagnosis_error", None)
            session.pop("diagnosis_v3_error", None)
            session.pop("diagnosis_v3_identity_error", None)
        elif result.get("error"):
            session["diagnosis_error"] = str(result["error"])
        updated = self._store.replace_session(session)

        return {
            "session": updated,
            "diagnostic": {
                "correlation_id": str(correlation_id),
                "status": result.get("status", "pending"),
                "evidence_count": len(evidence_items),
                "snapshot_types": list(snap_by_type.keys()),
                "snapshot_count": len(snapshots),
            },
            "source": source,
        }

    def refresh_diagnosis_status(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        correlation_id = self._parse_uuid(session.get("diagnosis_correlation_id"))
        if correlation_id is None:
            return {
                "session": session,
                "diagnostic": {"status": "not_requested"},
                "source": "local",
            }

        try:
            from cous.clients.diagnosis import DiagnosisClient

            diag = DiagnosisClient(self._config, self._http._token_provider)
            result = diag.diagnosis_status(correlation_id)
            source = "v3-remote"
        except Exception as exc:
            result = {
                "correlation_id": str(correlation_id),
                "status": session.get("diagnosis_status") or "unknown",
                "error_message": str(exc),
            }
            source = "v3-status-unavailable"

        previous_status = str(session.get("diagnosis_status") or "")
        remote_status = str(result.get("status") or "").strip()
        if remote_status == "unknown" and previous_status in {"queued", "processing"}:
            status = previous_status
        else:
            status = remote_status or previous_status or "unknown"
        remote_result = result.get("result") if isinstance(result.get("result"), dict) else None
        if remote_result is not None:
            session["diagnosis_result"] = remote_result
            session.pop("diagnosis_error", None)
        if status == "completed" and not session.get("diagnosis_result"):
            status = "awaiting_callback"
        session["diagnosis_status"] = status
        session["diagnosis_queue_status"] = result
        if result.get("attempts") is not None:
            session["diagnosis_attempts"] = int(result.get("attempts") or 0)
        if result.get("last_attempt_at"):
            session["diagnosis_last_attempt_at"] = str(result["last_attempt_at"])
        if result.get("error_message"):
            session["diagnosis_error"] = str(result["error_message"])

        updated = self._store.replace_session(session)
        return {
            "session": updated,
            "diagnostic": result,
            "source": source,
        }

    def diagnosis_runtime_status(self) -> dict[str, Any]:
        from cous.clients.diagnosis import DiagnosisClient

        diag = DiagnosisClient(self._config, self._http._token_provider)
        return diag.runtime_status()

    def _build_evidence_data(
        self,
        snap_type: str,
        snaps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": snap_type,
            "count": len(snaps),
            "sample_keys": list(snaps[0].keys())[:10] if snaps else [],
        }
        numeric: dict[str, list[float]] = {}
        for snap in snaps:
            for key, value in snap.items():
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                if not self._is_valid_numeric_sample(snap, key):
                    continue
                numeric.setdefault(key, []).append(float(value))

        for key, values in numeric.items():
            if not values:
                continue
            data[f"{key}_avg"] = sum(values) / len(values)
            data[f"{key}_min"] = min(values)
            data[f"{key}_max"] = max(values)
        return data

    def _is_valid_numeric_sample(self, snap: dict[str, Any], key: str) -> bool:
        valid_keys = [f"{key}_valid"]
        suffixes = (
            "_permille",
            "_mohm",
            "_uNm",
            "_mw",
            "_mv",
            "_mg",
            "_hz",
            "_um_s2",
            "_um_s",
            "_um",
            "_mm",
            "_us",
        )
        for suffix in suffixes:
            if key.endswith(suffix):
                valid_keys.append(f"{key[:-len(suffix)]}_valid")
        return all(
            not (valid_key in snap and snap[valid_key] is False)
            for valid_key in valid_keys
        )

    def _resolve_diagnosis_ids(
        self,
        session: dict[str, Any],
    ) -> tuple[dict[str, UUID], list[str]]:
        header = session.get("header") or {}
        candidates = {
            "capture_session_id": (
                session.get("capture_session_id")
                or session.get("remote_capture_session_id")
                or header.get("capture_session_id")
            ),
            "instance_id": (
                session.get("instance_id")
                or header.get("instance_id")
                or self._config.diagnosis_instance_id
            ),
            "domain_id": (
                session.get("domain_id")
                or header.get("domain_id")
                or self._config.diagnosis_domain_id
            ),
        }
        ids: dict[str, UUID] = {}
        missing: list[str] = []
        for key, value in candidates.items():
            parsed = self._parse_uuid(value)
            if parsed is None:
                missing.append(key)
            else:
                ids[key] = parsed
        return ids, missing

    def _parse_uuid(self, value: object) -> UUID | None:
        if isinstance(value, UUID):
            return value
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    def _resolve_remote_capture_identity(self, session: dict[str, Any]) -> dict[str, Any]:
        header = session.get("header") or {}
        payload = {
            "domain_name": self._config.diagnosis_domain_name,
            "domain_version": self._config.diagnosis_domain_version,
            "entity_type": self._config.diagnosis_entity_type,
            "manufacturer": str(header.get("fabricante") or ""),
            "model": str(header.get("modelo") or ""),
            "serial_number": str(
                header.get("numero_serie")
                or session.get("id")
                or "unknown"
            ),
            "operator_name": str(header.get("tecnico") or ""),
        }
        result = self._http.post(
            f"{self._runtime_url}/v3/operational/resolve-capture",
            payload,
        )
        updated = deepcopy(session)
        for key in (
            "domain_id",
            "entity_id",
            "instance_id",
            "operational_session_id",
            "capture_session_id",
        ):
            if result.get(key):
                updated[key] = str(result[key])
        return self._store.replace_session(updated)

    def _diagnose_local(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        diagnostic = {
            "approved": bool(session.get("valid_snapshots"))
            and not bool(session.get("invalid_snapshots")),
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
        self._diagnose_local(session_id)
        session = self.get_session(session_id)
        markdown = build_markdown_report(session)
        session["report_markdown"] = markdown
        session["status"] = "reported"
        updated = self._store.replace_session(session)
        return {"markdown": markdown, "session": updated, "source": "local"}

    def _merge_remote_session(
        self,
        local_session_id: str,
        remote_session: dict[str, Any],
    ) -> dict[str, Any]:
        session = self.get_session(local_session_id)
        if remote_session:
            session["remote_id"] = str(remote_session.get("id") or session.get("remote_id") or "")
            session["status"] = str(
                remote_session.get("status") or session.get("status") or "saved"
            )
            session["total_snapshots"] = int(
                remote_session.get("total_snapshots")
                or session.get("total_snapshots")
                or 0
            )
            session["valid_snapshots"] = int(
                remote_session.get("valid_snapshots")
                or session.get("valid_snapshots")
                or 0
            )
            session["invalid_snapshots"] = int(
                remote_session.get("invalid_snapshots")
                or session.get("invalid_snapshots")
                or 0
            )
            session["diagnostic"] = remote_session.get("diagnostic") or session.get("diagnostic")
            session["report_markdown"] = remote_session.get(
                "report_markdown"
            ) or session.get("report_markdown")
        session["sync_status"] = "synced"
        session["last_sync_error"] = ""
        return self._store.replace_session(session)

    def get_verticals(self) -> tuple[str, ...]:
        """
        Retorna verticais suportadas.
        Tenta endpoint remoto; usa DEFAULT_VERTICALS como fallback.
        """
        try:
            result = self._http.get(f"{self._runtime_url}/measurements/verticals")
            verticals = result.get("verticals")
            if isinstance(verticals, list) and verticals:
                return tuple(str(v) for v in verticals)
        except Exception:
            pass
        return DEFAULT_VERTICALS

    def close(self) -> None:
        self._http.close()
