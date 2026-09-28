"""Delivery of COUS telemetry sessions to SystemOS."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from cous.clients.base import ClientError
from cous.config import SystemOsConfig

_BATCH_SIZE = 50
_RETRYABLE_STATUS = {429, 502, 503, 504}
_SUPPORTED_TYPES = {
    "electromechanical_observation_frame",
    "electromechanical_correlation_frame",
    "electromechanical_signature",
    "hall_snapshot",
    "power_snapshot",
    "power_envelope_snapshot",
    "vibration_snapshot",
    "course_snapshot",
    "voltage_waveform_snapshot",
    "magnetic_sample",
}


class SystemOsTelemetryClient:
    def __init__(
        self,
        config: SystemOsConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._http = http_client or httpx.Client(timeout=httpx.Timeout(config.timeout))
        self._owns_http_client = http_client is None

    def sync_session(self, session: dict[str, Any]) -> dict[str, Any]:
        organization_id = self._config.organization_id.strip()
        if not organization_id:
            raise ClientError("SystemOS organization_id nao configurado")
        api_key = self._load_api_key()
        if not api_key:
            raise ClientError(
                "Chave SystemOS ausente na variavel "
                f"{self._config.api_key_env_var} e no arquivo {self._config.api_key_file}"
            )

        session_id = str(session.get("id") or "").strip()
        header = session.get("header") or {}
        service_order = str(header.get("ordem_servico") or "").strip()
        serial_number = str(header.get("numero_serie") or "").strip()
        captured_at = str(session.get("created_at") or "").strip()
        frames = list(session.get("snapshots") or [])
        if not session_id:
            raise ClientError("Sessao COUS sem identificador")
        if not service_order:
            raise ClientError("Sessao COUS sem numero da ordem de servico")
        if not frames:
            raise ClientError("Sessao COUS sem frames para enviar")

        unsupported = sorted(
            {str(frame.get("type") or "") for frame in frames}
            - _SUPPORTED_TYPES
        )
        if unsupported:
            raise ClientError(
                "SystemOS nao reconhece os tipos de frame: " + ", ".join(unsupported)
            )

        device_id = str(header.get("dispositivo_id") or "").strip()
        if not device_id:
            port = str(header.get("porta_serial") or "serial").strip()
            device_id = f"{socket.gethostname()}:{port}"

        receipts: list[dict[str, Any]] = []
        batches = [frames[index:index + _BATCH_SIZE] for index in range(0, len(frames), _BATCH_SIZE)]
        for index, batch in enumerate(batches):
            payload = {
                "organizacaoId": organization_id,
                "ordemNumero": service_order,
                "dispositivoId": device_id,
                "sessaoOrigemId": session_id,
                "numeroSerie": serial_number or None,
                "chaveIdempotencia": f"cous:{session_id}:{index:04d}",
                "frames": batch,
            }
            if captured_at:
                payload["recebidoEm"] = captured_at
            if str(header.get("tipo_coleta") or "").strip():
                payload["tipoColeta"] = str(header["tipo_coleta"]).strip()
            if str(header.get("observacoes") or "").strip():
                payload["observacoesColeta"] = str(header["observacoes"]).strip()
            receipts.append(self._post_batch(payload, api_key))
        return {
            "status": "synced",
            "batch_count": len(receipts),
            "frame_count": len(frames),
            "lot_ids": [str(item.get("id") or "") for item in receipts],
        }

    def _post_batch(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        url = f"{self._config.base_url}/integracoes/medicoes/lotes"
        for attempt in range(3):
            try:
                response = self._http.post(
                    url,
                    json=payload,
                    headers={"x-tdma-key": api_key},
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ClientError(f"Falha de conexao com SystemOS: {exc}") from exc
            if response.status_code in _RETRYABLE_STATUS and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            if not response.is_success:
                detail = response.text[:300]
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        detail = str(data.get("message") or data.get("error") or data)[:300]
                except ValueError:
                    pass
                raise ClientError(
                    f"SystemOS HTTP {response.status_code}: {detail}",
                    status_code=response.status_code,
                )
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}
        raise ClientError("Falha apos todas as tentativas no SystemOS")

    def _load_api_key(self) -> str:
        from_environment = os.environ.get(self._config.api_key_env_var, "").strip()
        if from_environment:
            return from_environment
        path = Path(os.path.expandvars(os.path.expanduser(self._config.api_key_file)))
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()
