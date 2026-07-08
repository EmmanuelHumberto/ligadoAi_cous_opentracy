"""Schemas Pydantic para contratos COUS v3.0 — Documento IV.

Define os payloads formais de comunicação entre componentes:
- Firmware → Cous: assinatura eletromecânica + desvios
- Cous → OpenTracy: requisição de diagnóstico
- OpenTracy → Cous: callback de diagnóstico
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Firmware → Cous ──────────────────────────────────────────────────────

class InstanceRefSchema(BaseModel):
    serial_number: str = Field(min_length=1)


class SignatureDataSchema(BaseModel):
    timestamp_us: int = Field(ge=0)
    valid: bool = True
    rpm: float | None = None
    motor_current_ma: float | None = None
    voltage_mv: float | None = None
    bemf_v: float | None = None
    equivalent_resistance_mohm: float | None = None
    torque_load_permille: float | None = None


class DeviationDataSchema(BaseModel):
    bemf_error_permille: float | None = None
    equivalent_resistance_error_permille: float | None = None
    torque_error_permille: float | None = None
    current_error_permille: float | None = None


class FirmwareSignaturePayload(BaseModel):
    """Payload v3.0: Firmware → Cous (assinatura + desvios)."""

    schema_version: str = "3.0"
    capture_session_id: UUID
    instance: InstanceRefSchema
    profile_label: str = Field(min_length=1)
    signature: SignatureDataSchema
    deviations: DeviationDataSchema = Field(default_factory=DeviationDataSchema)

    @field_validator("schema_version")
    @classmethod
    def check_version(cls, v: str) -> str:
        if v not in {"3.0", "3"}:
            raise ValueError(f"schema_version deve ser '3.0'. Recebido: {v}")
        return "3.0"


class FirmwareCaptureClosePayload(BaseModel):
    """Payload v3.0: Firmware → Cous (encerramento de captura)."""

    schema_version: str = "3.0"
    capture_session_id: UUID
    instance_id: UUID
    valid_ratio: float = Field(ge=0.0, le=1.0)
    total_signatures: int = Field(ge=0)
    valid_signatures: int = Field(ge=0)
    ended_at: datetime


# ── Cous → OpenTracy (Diagnóstico) ───────────────────────────────────────

class EvidenceItemSchema(BaseModel):
    evidence_id: UUID
    evidence_type: str
    evidence_strength: str = "weak"
    source_reference: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data: dict[str, Any] = Field(default_factory=dict)


class DiagnosisContextSchema(BaseModel):
    reported_problem: str | None = None
    instance_history_summary: str | None = None


class DiagnosisRequestPayload(BaseModel):
    """Payload v3.0: Cous → OpenTracy (requisição de diagnóstico)."""

    schema_version: str = "3.0"
    correlation_id: UUID
    operation: str = "diagnosis_request"
    capture_session_id: UUID
    instance_id: UUID
    domain_id: UUID
    priority: str = "normal"
    queued_at: datetime
    callback_endpoint: str
    evidence_set: list[EvidenceItemSchema] = Field(default_factory=list)
    context: DiagnosisContextSchema = Field(default_factory=DiagnosisContextSchema)


# ── OpenTracy → Cous (Callback) ──────────────────────────────────────────

class ConfidenceBreakdownSchema(BaseModel):
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    document_score: float = Field(default=0.0, ge=0.0, le=1.0)
    history_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)


class HypothesisResultSchema(BaseModel):
    hypothesis_id: UUID
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_breakdown: ConfidenceBreakdownSchema | None = None
    is_primary: bool = False
    causal_chain_id: UUID | None = None


class ExplanationResultSchema(BaseModel):
    narrative: str
    narrative_type: str = "technical"
    evidence_ids: list[UUID] = Field(default_factory=list)
    knowledge_units_applied: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class DiagnosisCallbackPayload(BaseModel):
    """Payload v3.0: OpenTracy → Cous (resultado do diagnóstico)."""

    schema_version: str = "3.0"
    correlation_id: UUID
    capture_session_id: UUID
    trace_id: UUID
    duration_ms: int = Field(ge=0)
    hypotheses: list[HypothesisResultSchema] = Field(default_factory=list)
    explanation: ExplanationResultSchema | None = None
    error: str | None = None


# ── Diagnóstico legado (compatibilidade) ─────────────────────────────────

class LegacySignaturePayload(BaseModel):
    """Payload legado sem schema_version — compatibilidade binária."""

    capture_session_id: UUID | None = None
    instance: InstanceRefSchema | None = None
    signature: dict[str, Any] = Field(default_factory=dict)
    deviations: dict[str, Any] | None = None
    # Campos extras ignorados
    model_config = {"extra": "allow"}
