"""Validation helpers for measurement data before persistence."""

from __future__ import annotations

from typing import Any

from cous.measurements.constants import DEFAULT_VERTICALS
from cous.measurements.serial_capture import normalize_snapshot_type


def validate_header(header: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tipo_coleta = str(header.get("tipo_coleta") or "").strip().lower()
    verticais = header.get("verticais") or []
    if not tipo_coleta:
        errors.append("tipo_coleta obrigatorio")
    if tipo_coleta in {"reparo", "pos-reparo"} and not str(
        header.get("peca_substituida") or ""
    ).strip():
        errors.append("peca_substituida obrigatoria para reparo/pos-reparo")
    if not verticais:
        errors.append("selecione ao menos uma vertical")
    baudrate = header.get("baudrate")
    if baudrate is not None and int(baudrate) <= 0:
        errors.append("baudrate deve ser positivo")
    duration = header.get("duracao_seg")
    if duration is not None and float(duration) <= 0:
        errors.append("duracao_seg deve ser positiva")
    curso_nominal = header.get("curso_nominal_mm")
    curso_min = header.get("curso_min_mm")
    curso_max = header.get("curso_max_mm")
    if (
        curso_nominal is not None
        and curso_min is not None
        and curso_max is not None
        and not (float(curso_min) <= float(curso_nominal) <= float(curso_max))
    ):
        errors.append("curso_nominal_mm deve ficar entre curso_min_mm e curso_max_mm")
    unknown = {
        normalize_snapshot_type(item)
        for item in verticais
        if normalize_snapshot_type(item) not in DEFAULT_VERTICALS
    }
    if unknown:
        errors.append(f"verticais invalidas: {', '.join(sorted(unknown))}")
    return errors


def validate_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    allowed_types: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for snapshot in snapshots:
        errors = _validate_snapshot(snapshot, allowed_types)
        if errors:
            rejected.append(
                {
                    "snapshot": snapshot,
                    "errors": errors,
                }
            )
            continue
        valid.append(snapshot)
    return valid, rejected


def _validate_snapshot(snapshot: dict[str, Any], allowed_types: set[str]) -> list[str]:
    errors: list[str] = []
    snapshot_type = normalize_snapshot_type(snapshot.get("type"))
    # Inferir tipo para snaps sem campo type (ex: raw magnético)
    if "type" not in snapshot:
        from cous.measurements.serial_capture import _infer_snapshot_type
        snapshot_type = _infer_snapshot_type(snapshot)
    if snapshot_type not in allowed_types:
        errors.append("tipo nao permitido para a sessao")
    if "type" not in snapshot and snapshot_type == "unknown":
        errors.append("campo type ausente e tipo nao pode ser inferido")
    timestamp = snapshot.get("timestamp_us")
    if timestamp is None:
        errors.append("campo timestamp_us obrigatorio")
    else:
        try:
            if int(timestamp) < 0:
                errors.append("timestamp_us deve ser >= 0")
        except (TypeError, ValueError):
            errors.append("timestamp_us invalido")
    if len(snapshot) <= 1:
        errors.append("snapshot sem payload util")
    return errors
