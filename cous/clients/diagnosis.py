"""Cliente HTTP para diagnóstico COUS v3.0 — Cous → OpenTracy.

Envia requisições de diagnóstico para o OpenTracy Runtime e recebe
callbacks com hipóteses e explicações.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from cous.auth import TokenProvider
from cous.clients.base import AuthenticatedHttpClient, ClientError
from cous.config import OpenTracyConfig
from cous.contracts.v3_schemas import (
    DiagnosisCallbackPayload,
    DiagnosisRequestPayload,
)
from cous.measurements.store import MeasurementLocalStore

logger = logging.getLogger("cous.diagnosis")


class DiagnosisClient:
    """Cliente para o endpoint /v3/diagnosis do OpenTracy Runtime."""

    def __init__(self, config: OpenTracyConfig, token_provider: TokenProvider) -> None:
        self._http = AuthenticatedHttpClient(
            token_provider=token_provider,
            timeout=config.timeout,
        )
        self._runtime_url = config.runtime_url.rstrip("/")

    def request_diagnosis(self, payload: DiagnosisRequestPayload) -> dict[str, Any]:
        """Envia requisição de diagnóstico (assíncrono).

        Retorna resposta imediata com status da fila.
        O resultado chega via callback.
        """
        try:
            return self._http.post(
                f"{self._runtime_url}/v3/diagnosis",
                payload.model_dump(mode="json"),
            )
        except ClientError as e:
            logger.error("Falha ao enfileirar diagnóstico: %s", e)
            raise

    def diagnosis_status(self, correlation_id: UUID) -> dict[str, Any]:
        """Consulta status de um diagnóstico enfileirado."""
        try:
            return self._http.get(
                f"{self._runtime_url}/v3/diagnosis/{correlation_id}"
            )
        except ClientError:
            return {"status": "unknown", "correlation_id": str(correlation_id)}

    def runtime_status(self) -> dict[str, Any]:
        """Consulta disponibilidade do runtime de diagnóstico."""
        return self._http.get(f"{self._runtime_url}/v3/diagnosis/status")

    def health(self) -> bool:
        """Verifica se o runtime está acessível."""
        try:
            return self._http.get(f"{self._runtime_url}/health").get("status") == "ok"
        except Exception:
            return False

    def close(self) -> None:
        self._http.close()


class DiagnosisCallbackHandler:
    """Handler para callbacks de diagnóstico (OpenTracy → Cous).

    Registrado como endpoint HTTP no Cous para receber resultados.
    """

    def __init__(self, store: MeasurementLocalStore | None = None) -> None:
        self._store = store
        self._results: dict[UUID, DiagnosisCallbackPayload] = {}
        self._pending: set[UUID] = set()

    def register_pending(self, correlation_id: UUID) -> None:
        self._pending.add(correlation_id)

    def handle_callback(self, payload: DiagnosisCallbackPayload) -> None:
        """Processa callback de diagnóstico recebido do OpenTracy."""
        self._results[payload.correlation_id] = payload
        self._pending.discard(payload.correlation_id)
        if self._store is not None:
            updated = self._store.apply_diagnosis_callback(
                str(payload.correlation_id),
                str(payload.capture_session_id),
                payload.model_dump(mode="json"),
            )
            if updated is None:
                raise ValueError(
                    "Sessao local nao encontrada para callback de diagnostico: "
                    f"correlation_id={payload.correlation_id} "
                    f"capture_session_id={payload.capture_session_id}"
                )
        logger.info(
            "Diagnóstico recebido: correlation_id=%s, duration_ms=%d, hypotheses=%d",
            payload.correlation_id,
            payload.duration_ms,
            len(payload.hypotheses),
        )

    def get_result(self, correlation_id: UUID) -> DiagnosisCallbackPayload | None:
        return self._results.get(correlation_id)

    def is_pending(self, correlation_id: UUID) -> bool:
        return correlation_id in self._pending

    @property
    def pending_count(self) -> int:
        return len(self._pending)
