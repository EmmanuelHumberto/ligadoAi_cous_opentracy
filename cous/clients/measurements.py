"""Client for OpenTracy measurements endpoints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

from cous.auth import TokenProvider
from cous.clients.base import AuthenticatedHttpClient
from cous.config import OpenTracyConfig, SystemOsConfig
from cous.clients.systemos import SystemOsTelemetryClient
from cous.measurements.analysis import (
    append_opentracy_diagnosis,
    build_chat_context,
    build_markdown_report,
    build_recent_summary,
    filter_sessions,
)
from cous.measurements.constants import DEFAULT_VERTICALS
from cous.measurements.electromechanical import (
    CORRELATION_TYPE,
    OBSERVATION_TYPE,
    build_electromechanical_evidence,
    build_local_diagnostic,
    electromechanical_evidence_rating,
)
from cous.measurements.serial_capture import normalize_snapshot_type, normalize_verticals
from cous.measurements.store import MeasurementLocalStore
from cous.measurements.validation import validate_header, validate_snapshots


class MeasurementsClient:
    def __init__(
        self,
        config: OpenTracyConfig,
        token_provider: TokenProvider,
        store: MeasurementLocalStore,
        systemos_config: SystemOsConfig | None = None,
    ) -> None:
        self._http = AuthenticatedHttpClient(
            token_provider=token_provider,
            timeout=config.timeout,
        )
        self._runtime_url = config.runtime_url.rstrip("/")
        self._config = config
        self._store = store
        self._systemos = (
            SystemOsTelemetryClient(systemos_config)
            if systemos_config is not None and systemos_config.enabled
            else None
        )

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
        errors: list[str] = []
        try:
            self._sync_opentracy_session(session_id)
        except Exception as exc:
            errors.append(f"OpenTracy: {exc}")
        try:
            self.sync_systemos_session(session_id)
        except Exception as exc:
            errors.append(f"SystemOS: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
        return self.get_session(session_id)

    def _sync_opentracy_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        header = deepcopy(session.get("header") or {})
        local_source_id = str(session.get("id") or session_id)
        header["source_session_id"] = local_source_id
        remote_id = str(session.get("remote_id") or "")
        try:
            if remote_id:
                remote_session = self._http.get(
                    f"{self._runtime_url}/measurements/sessions/{remote_id}"
                )
                remote_header = remote_session.get("header") or {}
                if remote_header.get("source_session_id") != local_source_id:
                    self._set_remote_source_identity(remote_id, local_source_id)
            else:
                remote_session = self._http.post(
                    f"{self._runtime_url}/measurements/sessions",
                    {"header": header},
                )
                remote_id = str(remote_session.get("id") or "")
            snapshots = deepcopy(session.get("snapshots") or [])
            if snapshots:
                remote_snapshots = self._prepare_remote_snapshots(
                    str(session.get("id") or session_id),
                    snapshots,
                )
                ingestion = self._http.post(
                    f"{self._runtime_url}/measurements/sessions/{remote_id}/snapshots",
                    {"snapshots": remote_snapshots},
                )
                accepted = int(ingestion.get("accepted") or 0)
                rejected = int(ingestion.get("rejected") or 0)
                duplicates = int(ingestion.get("duplicates") or 0)
                accounted = accepted + rejected + duplicates
                if rejected:
                    details = ingestion.get("errors") or []
                    raise RuntimeError(
                        f"OpenTracy rejected {rejected} of {len(snapshots)} snapshots: "
                        f"{details}"
                    )
                if accounted != len(snapshots):
                    raise RuntimeError(
                        "OpenTracy returned an incomplete ingestion receipt: "
                        f"expected={len(snapshots)} accounted={accounted}"
                    )
                session["sync_receipt"] = {
                    "accepted": accepted,
                    "rejected": rejected,
                    "duplicates": duplicates,
                }
            session["remote_id"] = remote_id
            session["sync_status"] = "synced"
            session["last_sync_error"] = ""
            return self._store.replace_session(session)
        except Exception as exc:
            session["sync_status"] = "sync_failed"
            session["last_sync_error"] = str(exc)
            self._store.replace_session(session)
            raise

    def sync_systemos_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if self._systemos is None:
            return session
        try:
            receipt = self._systemos.sync_session(session)
            session["systemos_sync_status"] = "synced"
            session["systemos_sync_receipt"] = receipt
            session["last_systemos_sync_error"] = ""
            return self._store.replace_session(session)
        except Exception as exc:
            session["systemos_sync_status"] = "sync_failed"
            session["last_systemos_sync_error"] = str(exc)
            self._store.replace_session(session)
            raise

    def _prepare_remote_snapshots(
        self,
        session_id: str,
        snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for snapshot in snapshots:
            item = deepcopy(snapshot)
            canonical = json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            item["event_id"] = f"tma:{session_id}:{digest}"
            prepared.append(item)
        return prepared

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
            and (
                str(session.get("sync_status") or "") != "synced"
                or (
                    self._systemos is not None
                    and str(session.get("systemos_sync_status") or "") != "synced"
                )
            )
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
        markdown = append_opentracy_diagnosis(markdown, updated)
        if markdown != updated.get("report_markdown"):
            updated["report_markdown"] = markdown
            updated = self._store.replace_session(updated)
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
        local_diagnostic = build_local_diagnostic(
            snapshots,
            valid_snapshots=int(session.get("valid_snapshots") or 0),
            invalid_snapshots=int(session.get("invalid_snapshots") or 0),
        )
        local_diagnostic["header"] = deepcopy(header)
        local_diagnostic["type_counts"] = deepcopy(
            session.get("snapshots_by_type") or {}
        )
        session["diagnostic"] = local_diagnostic
        session = self._store.replace_session(session)

        # Montar evidence_set a partir dos snapshots
        # Agrupar por tipo e extrair métricas relevantes
        evidence_items: list[EvidenceItemSchema] = []
        snap_by_type: dict[str, list[dict]] = {}
        for snap in snapshots:
            t = snap.get("type", "unknown")
            snap_by_type.setdefault(t, []).append(snap)

        for snap_type, snaps in snap_by_type.items():
            evidence_data = self._build_evidence_data(snap_type, snaps)
            if snap_type in {OBSERVATION_TYPE, CORRELATION_TYPE}:
                evidence_strength, confidence = electromechanical_evidence_rating(
                    snap_type,
                    evidence_data,
                )
            else:
                evidence_strength = "moderate" if len(snaps) > 50 else "weak"
                confidence = min(len(snaps) / 200.0, 1.0)
            evidence = EvidenceItemSchema(
                evidence_id=uuid4(),
                evidence_type="physical",
                evidence_strength=evidence_strength,
                source_reference=f"capture:{session_id}:{snap_type}",
                confidence=confidence,
                data=evidence_data,
            )
            evidence_items.append(evidence)

        service_order_number = str(header.get("ordem_servico") or "").strip()
        equipment_serial_number = str(header.get("numero_serie") or "").strip()
        measurement_observations = str(header.get("observacoes") or "").strip()
        evidence_items.append(
            EvidenceItemSchema(
                evidence_id=uuid4(),
                evidence_type="service_order_context",
                evidence_strength="weak",
                source_reference=f"service-order:{service_order_number}",
                confidence=0.35 if measurement_observations else 0.2,
                data={
                    "type": "service_order_context",
                    "service_order_number": service_order_number or None,
                    "equipment_serial_number": equipment_serial_number,
                    "observations": measurement_observations,
                    "epistemic_role": "reported_context",
                },
            )
        )

        correlation_id = uuid4()
        ids, missing_ids = self._resolve_diagnosis_ids(session)
        if missing_ids and self._config.diagnosis_auto_resolve_identity:
            try:
                session = self._resolve_remote_capture_identity(session)
                ids, missing_ids = self._resolve_diagnosis_ids(session)
            except Exception as exc:
                session["diagnosis_v3_identity_error"] = str(exc)

        if missing_ids:
            error = "Diagnostico v3 requer IDs reais: " + ", ".join(missing_ids)
            session["diagnosis_correlation_id"] = str(correlation_id)
            session["diagnosis_status"] = "local_fallback"
            session["diagnosis_v3_error"] = error
            updated = self._store.replace_session(session)
            diagnostic = deepcopy(local_diagnostic)
            diagnostic.update(
                {
                    "correlation_id": str(correlation_id),
                    "queue_status": "local_fallback",
                    "error": error,
                    "evidence_count": len(evidence_items),
                    "snapshot_types": list(snap_by_type.keys()),
                    "snapshot_count": len(snapshots),
                }
            )
            return {
                "session": updated,
                "diagnostic": diagnostic,
                "source": "v3-local-fallback",
            }

        try:
            session = self._synchronize_capture_projection(
                session,
                ids["capture_session_id"],
            )
        except Exception as exc:
            session = self.get_session(session_id)
            session["capture_projection_status"] = "failed"
            session["capture_projection_error"] = str(exc)
            session = self._store.replace_session(session)

        if service_order_number:
            reported_problem = (
                f"OS {service_order_number}: {measurement_observations}"
                if measurement_observations
                else f"OS {service_order_number}"
            )
        else:
            reported_problem = measurement_observations or None

        payload = DiagnosisRequestPayload(
            correlation_id=correlation_id,
            capture_session_id=ids["capture_session_id"],
            instance_id=ids["instance_id"],
            domain_id=ids["domain_id"],
            queued_at=datetime.now(UTC),
            callback_endpoint=self._config.diagnosis_callback_endpoint,
            evidence_set=evidence_items,
            context=DiagnosisContextSchema(
                service_order_number=service_order_number or None,
                equipment_serial_number=equipment_serial_number or None,
                measurement_observations=measurement_observations or None,
                reported_problem=reported_problem,
                instance_history_summary=(
                    f"{header.get('fabricante','?')} {header.get('modelo','?')} "
                    f"— serie {equipment_serial_number}; {len(snapshots)} snapshots"
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
            error = str(e)
            session["diagnosis_correlation_id"] = str(correlation_id)
            session["diagnosis_status"] = "local_fallback"
            session["diagnosis_v3_payload"] = payload.model_dump(mode="json")
            session["diagnosis_v3_error"] = error
            updated = self._store.replace_session(session)
            diagnostic = deepcopy(local_diagnostic)
            diagnostic.update(
                {
                    "correlation_id": str(correlation_id),
                    "queue_status": "local_fallback",
                    "error": error,
                    "evidence_count": len(evidence_items),
                    "snapshot_types": list(snap_by_type.keys()),
                    "snapshot_count": len(snapshots),
                }
            )
            return {
                "session": updated,
                "diagnostic": diagnostic,
                "source": "v3-local-fallback",
            }

        # Armazenar correlation_id na sessão
        session["diagnosis_correlation_id"] = str(correlation_id)
        session["diagnosis_status"] = result.get("status", "unknown")
        session["diagnosis_v3_payload"] = payload.model_dump(mode="json")
        session.pop("diagnosis_result", None)
        session.pop("diagnosis_completed_at", None)
        session.pop("diagnosis_attempts", None)
        session.pop("diagnosis_last_attempt_at", None)
        session.pop("diagnosis_queue_status", None)
        session.pop("diagnosis_callback_status", None)
        session.pop("diagnosis_callback_attempts", None)
        session.pop("diagnosis_callback_error", None)
        if source == "v3-remote":
            session.pop("diagnosis_error", None)
            session.pop("diagnosis_v3_error", None)
            session.pop("diagnosis_v3_identity_error", None)
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
        if result.get("callback_status"):
            session["diagnosis_callback_status"] = str(result["callback_status"])
        if result.get("callback_attempts") is not None:
            session["diagnosis_callback_attempts"] = int(
                result.get("callback_attempts") or 0
            )
        if result.get("callback_error"):
            session["diagnosis_callback_error"] = str(result["callback_error"])
        elif result.get("callback_status") == "delivered":
            session.pop("diagnosis_callback_error", None)

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
        if snap_type in {OBSERVATION_TYPE, CORRELATION_TYPE}:
            return build_electromechanical_evidence(snap_type, snaps)
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
        unavailable_mechanical_fields = {
            "stroke_inertial_torque_uNm",
            "required_torque_uNm",
            "torque_load_permille",
            "mechanical_equivalent_load_permille",
            "required_mechanical_power_mw",
            "drive_loss_permille",
            "mechanical_x_out_um",
            "mechanical_v_out_um_s",
            "mechanical_a_out_um_s2",
            "cartridge_preload_compression_um",
            "cartridge_dynamic_compression_um",
            "cartridge_compression_um",
            "cartridge_torque_envelope_uNm",
        }
        if key in unavailable_mechanical_fields:
            return False
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
            "service_order_number": str(header.get("ordem_servico") or ""),
            "measurement_observations": str(header.get("observacoes") or ""),
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
            "service_order_document_id",
        ):
            if result.get(key):
                updated[key] = str(result[key])
        return self._store.replace_session(updated)

    def _synchronize_capture_projection(
        self,
        session: dict[str, Any],
        capture_session_id: UUID,
    ) -> dict[str, Any]:
        local_id = str(session.get("id") or "")
        if not session.get("remote_id") or session.get("sync_status") != "synced":
            session = self.sync_session(local_id)
        remote_id = str(session.get("remote_id") or "")
        if not remote_id:
            raise RuntimeError("measurement synchronization returned no remote_id")
        self._set_remote_source_identity(remote_id, local_id)
        receipt = self._http.post(
            f"{self._runtime_url}/measurements/sessions/{remote_id}/capture-link",
            {"capture_session_id": str(capture_session_id)},
        )
        updated = self.get_session(local_id)
        updated["capture_projection_status"] = "projected"
        updated["capture_projection_receipt"] = deepcopy(receipt)
        updated.pop("capture_projection_error", None)
        return self._store.replace_session(updated)

    def _set_remote_source_identity(
        self,
        remote_id: str,
        source_session_id: str,
    ) -> None:
        self._http.put(
            f"{self._runtime_url}/measurements/sessions/{remote_id}/source-identity",
            {"source_session_id": source_session_id},
        )

    def _diagnose_local(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        diagnostic = build_local_diagnostic(
            session.get("snapshots") or [],
            valid_snapshots=int(session.get("valid_snapshots") or 0),
            invalid_snapshots=int(session.get("invalid_snapshots") or 0),
        )
        diagnostic["header"] = deepcopy(session.get("header") or {})
        diagnostic["type_counts"] = deepcopy(session.get("snapshots_by_type") or {})
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
        if self._systemos is not None:
            self._systemos.close()
