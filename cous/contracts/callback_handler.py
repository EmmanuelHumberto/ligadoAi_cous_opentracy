"""Callback HTTP handler — COUS v3.0 — OpenTracy → Cous.

Endpoint HTTP que o OpenTracy chama ao concluir um diagnóstico.
Registrado no próprio Cous para receber os resultados.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from cous.clients.diagnosis import DiagnosisCallbackHandler

logger = logging.getLogger("cous.callback")


class CallbackPayloadSchema(BaseModel):
    schema_version: str = "3.0"
    correlation_id: UUID
    capture_session_id: UUID
    trace_id: UUID
    duration_ms: int
    hypotheses: list[dict] = Field(default_factory=list)
    explanation: dict | None = None
    error: str | None = None


def create_callback_router(
    callback_handler: DiagnosisCallbackHandler,
) -> APIRouter:
    """Cria router FastAPI para receber callbacks de diagnóstico.

    Montado em /cous/diagnosis/callback no próprio Cous.
    """
    router = APIRouter(prefix="/cous/diagnosis", tags=["cous-callback"])

    @router.post("/callback", status_code=status.HTTP_200_OK)
    async def diagnosis_callback(payload: CallbackPayloadSchema) -> dict:
        """Recebe resultado de diagnóstico do OpenTracy."""
        from cous.contracts.v3_schemas import DiagnosisCallbackPayload

        callback = DiagnosisCallbackPayload(
            schema_version=payload.schema_version,
            correlation_id=payload.correlation_id,
            capture_session_id=payload.capture_session_id,
            trace_id=payload.trace_id,
            duration_ms=payload.duration_ms,
            hypotheses=payload.hypotheses,
            explanation=payload.explanation,
            error=payload.error,
        )
        try:
            callback_handler.handle_callback(callback)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        return {"status": "received", "correlation_id": str(payload.correlation_id)}

    @router.get("/callback/status")
    async def callback_status() -> dict:
        """Status do handler de callbacks."""
        return {
            "pending_count": callback_handler.pending_count,
        }

    return router
