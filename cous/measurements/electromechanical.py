"""Interpretation of firmware electromechanical telemetry contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from statistics import mean
from typing import Any

OBSERVATION_TYPE = "electromechanical_observation_frame"
CORRELATION_TYPE = "electromechanical_correlation_frame"
OBSERVATION_VERSION = 3
CORRELATION_VERSION = 4
MAX_CONFIRMATION_GAP_US = 5_000_000


class CorrelationLayer(IntEnum):
    OBSERVATION = 0
    TEMPORAL = 1
    PHYSICAL_CLOSURE = 2
    DIAGNOSTIC_HYPOTHESIS = 3


class RelationAssessment(IntEnum):
    OBSERVATION = 0
    CONSISTENT = 1
    SUSPECT = 2
    CRITICAL = 3
    INDETERMINATE = 4


@dataclass(frozen=True)
class ModeDefinition:
    label: str
    description: str


MODE_DEFINITIONS: dict[str, ModeDefinition] = {
    "locked_rotor_hypothesis": ModeDefinition(
        "Rotor travado",
        "Rotacao ausente com corrente igual ou superior a duas vezes a nominal.",
    ),
    "mechanical_decoupling_hypothesis": ModeDefinition(
        "Desacoplamento mecanico",
        "Motor proximo da curva em vazio, com FCEM alta e sem transferencia da carga declarada.",
    ),
    "motor_nominal_overload_hypothesis": ModeDefinition(
        "Sobrecarga do motor",
        "Corrente proxima ou superior a nominal, ou sistema energizado sem movimento.",
    ),
    "source_overvoltage_hypothesis": ModeDefinition(
        "Sobretensao da fonte",
        "Tensao aplicada superior a tensao nominal do perfil selecionado.",
    ),
    "source_interruption_hypothesis": ModeDefinition(
        "Interrupcao da fonte",
        "Envelope INA219 com queda sustentada proxima de zero durante uma janela energizada.",
    ),
    "source_sag_under_load_hypothesis": ModeDefinition(
        "Queda de tensao sob carga",
        "Aumento de corrente acompanhado por queda sustentada de tensao entre janelas.",
    ),
}

_ASSESSMENT_NAMES = {
    RelationAssessment.OBSERVATION: "observation",
    RelationAssessment.CONSISTENT: "consistent",
    RelationAssessment.SUSPECT: "suspect",
    RelationAssessment.CRITICAL: "critical",
    RelationAssessment.INDETERMINATE: "indeterminate",
}


def validate_aggregate_frame(snapshot: dict[str, Any]) -> list[str]:
    """Validate the documented type/version pair and its structural envelope."""
    snapshot_type = snapshot.get("type")
    if snapshot_type == OBSERVATION_TYPE:
        return _validate_observation(snapshot)
    if snapshot_type == CORRELATION_TYPE:
        return _validate_correlation(snapshot)
    return []


def summarize_electromechanical(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    observations = sorted(
        (item for item in snapshots if item.get("type") == OBSERVATION_TYPE),
        key=_timestamp,
    )
    correlations = sorted(
        (item for item in snapshots if item.get("type") == CORRELATION_TYPE),
        key=_timestamp,
    )
    if not observations and not correlations:
        return {}

    modes = _summarize_modes(correlations)
    active_modes = [mode for mode in modes if mode["active_now"]]
    persistent_modes = [mode for mode in modes if mode["max_consecutive_frames"] >= 2]
    latest_observation = observations[-1] if observations else {}
    latest_correlation = correlations[-1] if correlations else {}

    return {
        "observation_count": len(observations),
        "correlation_count": len(correlations),
        "valid_observation_ratio": _valid_ratio(observations),
        "valid_correlation_ratio": _valid_ratio(correlations),
        "latest_observation": _observation_digest(latest_observation),
        "latest_profile": _copy_mapping(latest_correlation.get("profile")),
        "latest_closure": _copy_mapping(latest_correlation.get("closure")),
        "latest_physical_signature": _copy_mapping(
            latest_correlation.get("physical_signature")
        ),
        "global_adherence_permille": _valid_numeric_average(
            correlations,
            "global_adherence_permille",
            "global_adherence_valid",
        ),
        "closure_complete_ratio": _boolean_ratio(correlations, "closure_complete"),
        "relations_truncated": any(
            item.get("relations_truncated") is True for item in correlations
        ),
        "modes": modes,
        "active_modes": active_modes,
        "persistent_modes": persistent_modes,
    }


def build_electromechanical_evidence(
    snapshot_type: str,
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build bounded evidence while preserving the nested physical meaning."""
    summary = summarize_electromechanical(snapshots)
    if snapshot_type == OBSERVATION_TYPE:
        return {
            "type": snapshot_type,
            "version": OBSERVATION_VERSION,
            "count": len(snapshots),
            "valid_ratio": summary.get("valid_observation_ratio"),
            "latest_observation": summary.get("latest_observation") or {},
        }
    return {
        "type": snapshot_type,
        "version": CORRELATION_VERSION,
        "count": len(snapshots),
        "valid_ratio": summary.get("valid_correlation_ratio"),
        "global_adherence_permille": summary.get("global_adherence_permille"),
        "closure_complete_ratio": summary.get("closure_complete_ratio"),
        "relations_truncated": summary.get("relations_truncated", False),
        "profile": summary.get("latest_profile") or {},
        "closure": summary.get("latest_closure") or {},
        "physical_signature": summary.get("latest_physical_signature") or {},
        "diagnostic_modes": summary.get("modes") or [],
    }


def electromechanical_evidence_rating(
    snapshot_type: str,
    evidence: dict[str, Any],
) -> tuple[str, float]:
    """Rate aggregate evidence from validity, persistence and declared confidence."""
    valid_ratio = evidence.get("valid_ratio")
    base_confidence = (
        max(0.0, min(1.0, float(valid_ratio)))
        if isinstance(valid_ratio, int | float) and not isinstance(valid_ratio, bool)
        else 0.0
    )
    if snapshot_type == OBSERVATION_TYPE:
        strength = "moderate" if evidence.get("count", 0) >= 2 else "weak"
        return strength, base_confidence

    active_modes = [
        mode
        for mode in evidence.get("diagnostic_modes", [])
        if isinstance(mode, dict) and mode.get("active_frames", 0) > 0
    ]
    if not active_modes:
        strength = "moderate" if evidence.get("count", 0) >= 2 else "weak"
        return strength, base_confidence

    mode_confidence = max(
        _permille(mode.get("confidence_permille_max")) / 1000.0
        for mode in active_modes
    )
    persistent = any(mode.get("persistent") is True for mode in active_modes)
    if persistent:
        return ("strong" if mode_confidence >= 0.8 else "moderate"), mode_confidence
    return "weak", mode_confidence


def build_local_diagnostic(
    snapshots: list[dict[str, Any]],
    *,
    valid_snapshots: int,
    invalid_snapshots: int,
) -> dict[str, Any]:
    """Classify collection quality and firmware hypotheses without overclaiming."""
    summary = summarize_electromechanical(snapshots)
    persistent = summary.get("persistent_modes") or []
    transient = [
        mode
        for mode in summary.get("modes") or []
        if mode.get("active_frames", 0) > 0 and not mode.get("persistent")
    ]
    active_now = summary.get("active_modes") or []
    assessment_available = bool(summary.get("correlation_count"))

    if persistent:
        status = "persistent_fault_hypothesis"
        text = (
            "Ha hipoteses de falha persistentes emitidas pelo firmware; "
            "elas exigem confirmacao tecnica."
        )
    elif transient:
        status = "transient_fault_hypothesis"
        text = (
            "Ha hipoteses de falha transitorias, sem persistencia temporal "
            "suficiente para classificacao."
        )
    elif assessment_available:
        status = "no_fault_hypothesis"
        text = "Nenhuma hipotese de falha ficou ativa nos frames de correlacao validos."
    elif valid_snapshots:
        status = "measurement_only"
        text = "Coleta valida, mas sem frame de correlacao para diagnostico fisico local."
    else:
        status = "no_valid_measurement"
        text = "Nenhum snapshot valido foi coletado."

    return {
        "approved": (
            bool(valid_snapshots)
            and not invalid_snapshots
            and not (persistent or transient)
        ),
        "collection_quality": (
            "valid"
            if valid_snapshots and not invalid_snapshots
            else "partial"
            if valid_snapshots
            else "invalid"
        ),
        "status": status,
        "summary": text,
        "technical_assessment_available": assessment_available,
        "requires_technical_confirmation": bool(persistent or transient),
        "total_snapshots": valid_snapshots + invalid_snapshots,
        "valid_snapshots": valid_snapshots,
        "invalid_snapshots": invalid_snapshots,
        "active_hypotheses": active_now,
        "persistent_hypotheses": persistent,
        "transient_hypotheses": transient,
        "electromechanical": summary,
    }


def _validate_observation(snapshot: dict[str, Any]) -> list[str]:
    errors = _validate_version(snapshot, OBSERVATION_VERSION)
    for key in ("valid", "channels", "hall", "power", "power_envelope", "vibration"):
        if key not in snapshot:
            errors.append(f"observation_frame sem campo {key}")
    if "channels" in snapshot and not isinstance(snapshot["channels"], dict):
        errors.append("observation_frame channels deve ser objeto")
    if "valid" in snapshot and not isinstance(snapshot["valid"], bool):
        errors.append("observation_frame valid deve ser booleano")
    for key in ("hall", "power", "power_envelope", "vibration", "course", "magnetic"):
        if key in snapshot and not isinstance(snapshot[key], dict):
            errors.append(f"observation_frame {key} deve ser objeto")
    vibration = snapshot.get("vibration")
    if isinstance(vibration, dict):
        for key in (
            "rpm_synchronous_rms_mg",
            "non_synchronous_rms_mg",
            "rpm_synchronous_energy_permille",
            "rpm_decomposition_confidence_permille",
            "rpm_decomposition_valid",
        ):
            if key not in vibration:
                errors.append(f"observation_frame vibration sem campo {key}")
    return errors


def _validate_correlation(snapshot: dict[str, Any]) -> list[str]:
    errors = _validate_version(snapshot, CORRELATION_VERSION)
    expected = {
        "valid": bool,
        "profile": dict,
        "axes": list,
        "physical_signature": dict,
        "closure": dict,
        "relation_count": int,
        "relations_truncated": bool,
        "relations": list,
    }
    for key, expected_type in expected.items():
        if key not in snapshot:
            errors.append(f"correlation_frame sem campo {key}")
        elif not isinstance(snapshot[key], expected_type):
            errors.append(
                f"correlation_frame {key} deve ser "
                f"{'lista' if expected_type is list else 'objeto/valor valido'}"
            )
    physical_signature = snapshot.get("physical_signature")
    if isinstance(physical_signature, dict):
        physical_axes = physical_signature.get("axes")
        if not isinstance(physical_axes, list):
            errors.append("correlation_frame physical_signature.axes deve ser lista")
        elif [axis.get("id") for axis in physical_axes if isinstance(axis, dict)] != list(range(6)):
            errors.append(
                "correlation_frame physical_signature.axes deve conter "
                "tensao, corrente, potencia, furacao, vibracao e RPM"
            )
    closure = snapshot.get("closure")
    motor = closure.get("motor") if isinstance(closure, dict) else None
    if not isinstance(motor, dict):
        errors.append("correlation_frame closure.motor deve ser objeto")
    else:
        for key in (
            "bemf_error_permille",
            "winding_resistance_error_permille",
            "rpm_error_permille",
            "electrical_power_error_permille",
        ):
            if key not in motor:
                errors.append(f"correlation_frame closure.motor sem campo {key}")
    relations = snapshot.get("relations")
    if isinstance(relations, list):
        declared_count = snapshot.get("relation_count")
        if isinstance(declared_count, int) and declared_count != len(relations):
            errors.append("correlation_frame relation_count difere de relations")
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict):
                errors.append(f"relation[{index}] deve ser objeto")
                continue
            for key in (
                "id",
                "layer",
                "assessment",
                "confidence_permille",
                "source_channels",
                "limitation",
                "valid",
            ):
                if key not in relation:
                    errors.append(f"relation[{index}] sem campo {key}")
            if relation.get("id") == "":
                errors.append(f"relation[{index}] id vazio")
            if relation.get("layer") not in {item.value for item in CorrelationLayer}:
                errors.append(f"relation[{index}] layer invalido")
            if relation.get("assessment") not in {
                item.value for item in RelationAssessment
            }:
                errors.append(f"relation[{index}] assessment invalido")
            confidence = relation.get("confidence_permille")
            if not isinstance(confidence, int) or isinstance(confidence, bool):
                errors.append(f"relation[{index}] confidence_permille invalido")
            elif not 0 <= confidence <= 1000:
                errors.append(f"relation[{index}] confidence_permille fora da faixa")
            if "valid" in relation and not isinstance(relation["valid"], bool):
                errors.append(f"relation[{index}] valid deve ser booleano")
            for key in ("id", "source_channels", "limitation"):
                if key in relation and not isinstance(relation[key], str):
                    errors.append(f"relation[{index}] {key} deve ser texto")
    return errors


def _validate_version(snapshot: dict[str, Any], expected: int) -> list[str]:
    version = snapshot.get("version")
    if version != expected:
        return [f"versao {version!r} incompatível; esperado {expected}"]
    return []


def _summarize_modes(correlations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for mode_id, definition in MODE_DEFINITIONS.items():
        state[mode_id] = {
            "id": mode_id,
            "label": definition.label,
            "description": definition.description,
            "observed_frames": 0,
            "active_frames": 0,
            "current_streak": 0,
            "max_consecutive_frames": 0,
            "active_now": False,
            "max_assessment": RelationAssessment.CONSISTENT,
            "confidence_values": [],
            "latest": None,
            "latest_active": None,
            "last_active_timestamp_us": None,
        }

    previous_session = None
    for frame in correlations:
        session = str(frame.get("source_session_id") or "")
        if session != previous_session:
            for mode in state.values():
                mode["current_streak"] = 0
                mode["last_active_timestamp_us"] = None
            previous_session = session
        relations = {
            item.get("id"): item
            for item in frame.get("relations", [])
            if isinstance(item, dict) and item.get("id") in MODE_DEFINITIONS
        }
        for mode_id, mode in state.items():
            relation = relations.get(mode_id)
            valid = bool(frame.get("valid") is True and frame.get("version") == CORRELATION_VERSION
                         and relation and relation.get("valid") is True)
            motor = _copy_mapping(_copy_mapping(frame.get("closure")).get("motor"))
            rpm_supported = motor.get("rpm_observation_valid") is True and motor.get("rpm_power_coherent") is True
            if mode_id == "locked_rotor_hypothesis" and not rpm_supported:
                valid = False
            if mode_id == "motor_nominal_overload_hypothesis" and not rpm_supported and relation:
                observed, reference = relation.get("observed"), relation.get("reference")
                if not (isinstance(observed, (int, float)) and isinstance(reference, (int, float))
                        and reference > 0 and abs(observed) >= 0.9 * reference):
                    valid = False
            assessment = _assessment(relation.get("assessment")) if valid else None
            active = assessment in {
                RelationAssessment.SUSPECT,
                RelationAssessment.CRITICAL,
            }
            mode["active_now"] = active
            if not valid:
                mode["current_streak"] = 0
                mode["last_active_timestamp_us"] = None
                continue
            mode["observed_frames"] += 1
            mode["latest"] = dict(relation)
            if active:
                timestamp_us = _timestamp(frame)
                previous_timestamp_us = mode["last_active_timestamp_us"]
                continuous = (
                    previous_timestamp_us is not None
                    and timestamp_us > previous_timestamp_us
                    and timestamp_us - previous_timestamp_us
                    <= MAX_CONFIRMATION_GAP_US
                )
                confidence = _permille(relation.get("confidence_permille"))
                mode["confidence_values"].append(confidence)
                mode["latest_active"] = dict(relation)
                mode["active_frames"] += 1
                mode["current_streak"] = mode["current_streak"] + 1 if continuous else 1
                mode["last_active_timestamp_us"] = timestamp_us
                mode["max_consecutive_frames"] = max(
                    mode["max_consecutive_frames"],
                    mode["current_streak"],
                )
                mode["max_assessment"] = max(mode["max_assessment"], assessment)
            else:
                mode["current_streak"] = 0
                mode["last_active_timestamp_us"] = None

    result: list[dict[str, Any]] = []
    for mode in state.values():
        if not mode["observed_frames"]:
            continue
        latest = mode.pop("latest_active") or mode.pop("latest") or {}
        mode.pop("latest", None)
        confidence_values = mode.pop("confidence_values")
        mode.pop("current_streak")
        mode.pop("last_active_timestamp_us")
        max_assessment = mode.pop("max_assessment")
        mode["assessment"] = _ASSESSMENT_NAMES[max_assessment]
        mode["confidence_permille_max"] = max(confidence_values, default=0)
        mode["confidence_permille_avg"] = (
            int(mean(confidence_values)) if confidence_values else 0
        )
        mode["persistent"] = mode["max_consecutive_frames"] >= 2
        mode["observed"] = latest.get("observed")
        mode["reference"] = latest.get("reference")
        mode["residual"] = latest.get("residual")
        mode["source_channels"] = latest.get("source_channels") or ""
        mode["limitation"] = latest.get("limitation") or ""
        result.append(mode)
    return result


def _observation_digest(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not snapshot:
        return {}
    return {
        "frame_id": snapshot.get("frame_id"),
        "timestamp_us": snapshot.get("timestamp_us"),
        "valid": snapshot.get("valid"),
        "coherent": snapshot.get("coherent"),
        "max_skew_us": snapshot.get("max_skew_us"),
        "channels": _copy_mapping(snapshot.get("channels")),
        "hall": _copy_mapping(snapshot.get("hall")),
        "power": _copy_mapping(snapshot.get("power")),
        "power_envelope": _copy_mapping(snapshot.get("power_envelope")),
        "vibration": _copy_mapping(snapshot.get("vibration")),
        "course": _copy_mapping(snapshot.get("course")),
        "magnetic": _copy_mapping(snapshot.get("magnetic")),
    }


def _copy_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _assessment(value: object) -> RelationAssessment | None:
    try:
        return RelationAssessment(int(value))
    except (TypeError, ValueError):
        return None


def _permille(value: object) -> int:
    try:
        return max(0, min(1000, int(value)))
    except (TypeError, ValueError):
        return 0


def _timestamp(snapshot: dict[str, Any]) -> int:
    try:
        return int(snapshot.get("timestamp_us") or 0)
    except (TypeError, ValueError):
        return 0


def _valid_ratio(snapshots: list[dict[str, Any]]) -> float | None:
    if not snapshots:
        return None
    return sum(item.get("valid") is True for item in snapshots) / len(snapshots)


def _boolean_ratio(snapshots: list[dict[str, Any]], key: str) -> float | None:
    values = [item[key] for item in snapshots if isinstance(item.get(key), bool)]
    if not values:
        return None
    return sum(value is True for value in values) / len(values)


def _valid_numeric_average(
    snapshots: list[dict[str, Any]],
    key: str,
    valid_key: str,
) -> float | None:
    values = [
        float(item[key])
        for item in snapshots
        if item.get(valid_key) is True
        and isinstance(item.get(key), int | float)
        and not isinstance(item.get(key), bool)
    ]
    return mean(values) if values else None
