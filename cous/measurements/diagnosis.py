"""Helpers for rendering persisted diagnosis results."""

from __future__ import annotations

from typing import Any


def diagnosis_summary_rows(session: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    status = str(session.get("diagnosis_status") or "").strip()
    correlation_id = str(session.get("diagnosis_correlation_id") or "").strip()
    raw_result = session.get("diagnosis_result")
    result = raw_result if isinstance(raw_result, dict) else {}
    result_correlation_id = str(result.get("correlation_id") or "").strip()
    if correlation_id and result_correlation_id and result_correlation_id != correlation_id:
        result = {}

    if not status and not correlation_id and not result:
        return rows

    rows.append(("Diagnostico", status or "desconhecido"))
    if correlation_id:
        rows.append(("Correlation ID", correlation_id))
    if session.get("diagnosis_completed_at"):
        rows.append(("Diagnostico concluido", str(session["diagnosis_completed_at"])))
    if session.get("diagnosis_attempts") is not None:
        rows.append(("Tentativas diagnostico", str(session["diagnosis_attempts"])))
    if session.get("diagnosis_last_attempt_at"):
        rows.append(("Ultima tentativa", str(session["diagnosis_last_attempt_at"])))
    if session.get("diagnosis_error"):
        rows.append(("Erro diagnostico", str(session["diagnosis_error"])))

    primary = _primary_hypothesis(result.get("hypotheses") if isinstance(result, dict) else None)
    if primary:
        description = str(primary.get("description") or "").strip()
        confidence = _format_confidence(primary.get("confidence"))
        if description and confidence:
            rows.append(("Hipotese principal", f"{description} ({confidence})"))
        elif description:
            rows.append(("Hipotese principal", description))

    explanation = result.get("explanation") if isinstance(result, dict) else None
    if isinstance(explanation, dict):
        narrative = str(explanation.get("narrative") or "").strip()
        confidence = _format_confidence(explanation.get("confidence"))
        if narrative and confidence:
            rows.append(("Explicacao", f"{narrative} ({confidence})"))
        elif narrative:
            rows.append(("Explicacao", narrative))

    return rows


def _primary_hypothesis(hypotheses: object) -> dict[str, Any] | None:
    if not isinstance(hypotheses, list):
        return None
    candidates = [item for item in hypotheses if isinstance(item, dict)]
    if not candidates:
        return None
    for item in candidates:
        if item.get("is_primary"):
            return item
    return candidates[0]


def _format_confidence(value: object) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{confidence:.0%}"
