from cous.auth import TokenProvider
from cous.clients.measurements import MeasurementsClient
from cous.config import OpenTracyConfig
from cous.measurements.analysis import build_markdown_report
from cous.measurements.electromechanical import (
    build_electromechanical_evidence,
    build_local_diagnostic,
    electromechanical_evidence_rating,
    summarize_electromechanical,
)
from cous.measurements.serial_capture import (
    collect_tma_snapshots_from_lines,
    normalize_verticals,
)
from cous.measurements.store import MeasurementLocalStore
from cous.measurements.validation import validate_snapshots


def _observation(timestamp_us: int = 1) -> dict:
    return {
        "type": "electromechanical_observation_frame",
        "version": 3,
        "frame_id": timestamp_us,
        "timestamp_us": timestamp_us,
        "valid": True,
        "coherent": True,
        "channels": {},
        "hall": {"valid": True, "frequency_hz": 100},
        "power": {"valid": True, "bus_voltage_mv": 6000, "current_ma": 900},
        "power_envelope": {"valid": True},
        "vibration": {
            "valid": True,
            "rpm_inferred": 0,
            "rpm_synchronous_rms_mg": 0,
            "non_synchronous_rms_mg": 0,
            "rpm_synchronous_energy_permille": 0,
            "rpm_decomposition_confidence_permille": 0,
            "rpm_decomposition_valid": False,
        },
        "course": {"valid": False},
        "magnetic": {"valid": False},
    }


def _correlation(
    timestamp_us: int,
    *,
    assessment: int,
    mode_id: str = "locked_rotor_hypothesis",
) -> dict:
    relation = {
        "id": mode_id,
        "layer": 3,
        "assessment": assessment,
        "observed": 900,
        "reference": 800,
        "residual": 100,
        "error_permille": 125,
        "confidence_permille": 850,
        "source_channels": "mpu,power,motor_nominal_current",
        "limitation": "requires technical confirmation",
        "valid": True,
    }
    return {
        "type": "electromechanical_correlation_frame",
        "version": 4,
        "frame_id": timestamp_us,
        "timestamp_us": timestamp_us,
        "valid": True,
        "global_adherence_permille": 920,
        "global_adherence_valid": True,
        "closure_level": 2,
        "closure_complete": True,
        "profile": {"valid": True, "id": "motor-test", "label": "Motor Test"},
        "axes": [],
        "physical_signature": {
            "valid": True,
            "axes": [{"id": axis_id} for axis_id in range(6)],
        },
        "closure": {
            "valid": True,
            "electrical": {"valid": True, "bus_voltage_mv": 6000},
            "motor": {
                "valid": True,
                "rpm_mpu": 0,
                "rpm_observation_valid": True,
                "rpm_power_coherent": True,
                "bemf_error_permille": 0,
                "winding_resistance_error_permille": 0,
                "rpm_error_permille": 0,
                "electrical_power_error_permille": 0,
            },
        },
        "relation_count": 1,
        "relations_truncated": False,
        "relations": [relation],
    }


def _client(tmp_path, monkeypatch) -> MeasurementsClient:
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = MeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    create_session = client.create_session
    client.create_session = lambda header: create_session(
        {
            "ordem_servico": "OS-TEST",
            "numero_serie": "SN-TEST",
            **header,
        }
    )
    return client


def test_capture_accepts_v3_and_v4_frames_as_signature_vertical():
    lines = [
        f"TMA_DATA {_json(_observation())}",
        f"TMA_DATA {_json(_correlation(2, assessment=3))}",
    ]

    snapshots = collect_tma_snapshots_from_lines(
        lines,
        allowed_types=normalize_verticals(["signature"]),
    )

    assert len(snapshots) == 2


def test_validation_rejects_wrong_contract_version():
    frame = _observation()
    frame["version"] = 1

    valid, rejected = validate_snapshots([frame], allowed_types={"signature"})

    assert valid == []
    assert "esperado 3" in rejected[0]["errors"][-1]


def test_diagnostic_requires_two_consecutive_active_frames_for_persistence():
    snapshots = [
        _correlation(1, assessment=3),
        _correlation(2, assessment=1),
        _correlation(3, assessment=3),
    ]

    transient = build_local_diagnostic(
        snapshots,
        valid_snapshots=3,
        invalid_snapshots=0,
    )
    persistent = build_local_diagnostic(
        snapshots + [_correlation(4, assessment=3)],
        valid_snapshots=4,
        invalid_snapshots=0,
    )

    assert transient["status"] == "transient_fault_hypothesis"
    assert transient["approved"] is False
    assert persistent["status"] == "persistent_fault_hypothesis"
    assert persistent["approved"] is False
    assert persistent["persistent_hypotheses"][0]["id"] == "locked_rotor_hypothesis"


def test_summary_distinguishes_current_and_historical_mode_state():
    snapshots = [
        _correlation(1, assessment=3),
        _correlation(2, assessment=3),
        _correlation(3, assessment=1),
    ]

    mode = summarize_electromechanical(snapshots)["modes"][0]

    assert mode["persistent"] is True
    assert mode["active_now"] is False
    assert mode["active_frames"] == 2
    assert mode["confidence_permille_max"] == 850


def test_diagnostic_does_not_join_active_frames_separated_by_long_gap():
    snapshots = [
        _correlation(1, assessment=3),
        _correlation(6_000_002, assessment=3),
    ]

    diagnostic = build_local_diagnostic(
        snapshots,
        valid_snapshots=2,
        invalid_snapshots=0,
    )

    assert diagnostic["status"] == "transient_fault_hypothesis"
    assert diagnostic["persistent_hypotheses"] == []


def test_remote_evidence_preserves_profile_closure_and_diagnostic_modes():
    snapshots = [
        _correlation(1, assessment=3),
        _correlation(2, assessment=3),
    ]

    evidence = build_electromechanical_evidence(
        "electromechanical_correlation_frame",
        snapshots,
    )

    assert evidence["profile"]["id"] == "motor-test"
    assert evidence["closure"]["motor"]["rpm_mpu"] == 0
    assert evidence["diagnostic_modes"][0]["persistent"] is True
    assert electromechanical_evidence_rating(
        "electromechanical_correlation_frame",
        evidence,
    ) == ("strong", 0.85)


def test_client_generates_fault_mode_diagnosis_and_report(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "Test",
            "modelo": "Machine",
            "tipo_coleta": "desempenho",
            "verticais": ["signature"],
            "baudrate": 115200,
            "duracao_seg": 10.0,
        }
    )
    result = client.add_snapshots(
        session["id"],
        [
            _observation(),
            _correlation(2, assessment=3),
            _correlation(3, assessment=3),
        ],
    )

    monkeypatch.setattr(
        client,
        "sync_session",
        lambda session_id: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    diagnostic = client.diagnose(session["id"])
    report = client.report(session["id"])

    assert result["accepted"] == 3
    assert diagnostic["diagnostic"]["status"] == "persistent_fault_hypothesis"
    assert diagnostic["diagnostic"]["approved"] is False
    assert "Rotor travado" in report["markdown"]
    assert "hipoteses emitidas pelo firmware" in report["markdown"]


def test_v3_fallback_returns_local_fault_mode_diagnosis(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "Test",
            "modelo": "Machine",
            "tipo_coleta": "desempenho",
            "verticais": ["signature"],
            "baudrate": 115200,
            "duracao_seg": 10.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            _correlation(1, assessment=3),
            _correlation(2, assessment=3),
        ],
    )

    result = client.diagnose_v3(session["id"])

    assert result["source"] == "v3-local-fallback"
    assert result["diagnostic"]["queue_status"] == "local_fallback"
    assert result["diagnostic"]["status"] == "persistent_fault_hypothesis"
    assert result["diagnostic"]["persistent_hypotheses"][0]["id"] == (
        "locked_rotor_hypothesis"
    )


def test_report_includes_persisted_opentracy_interpretation():
    correlation_id = "00000000-0000-0000-0000-0000000000d1"
    report = build_markdown_report(
        {
            "id": "session-1",
            "header": {"fabricante": "Test", "modelo": "Machine"},
            "snapshots": [_correlation(1, assessment=3)],
            "diagnosis_correlation_id": correlation_id,
            "diagnosis_result": {
                "correlation_id": correlation_id,
                "hypotheses": [
                    {
                        "description": "Rotor travado corroborado.",
                        "confidence": 0.72,
                        "is_primary": True,
                        "source": "firmware_mode_correlation",
                        "diagnostic_kind": "locked_rotor_hypothesis",
                        "corroborating_knowledge_units": ["ku-1"],
                        "limitations": ["confirmar por inspecao"],
                    }
                ],
                "explanation": {
                    "narrative": "OpenTracy correlacionou telemetria e conhecimento."
                },
            },
        }
    )

    assert "## Diagnostico OpenTracy" in report
    assert "Rotor travado corroborado" in report
    assert "Unidades de conhecimento corroborantes: 1" in report
    assert "OpenTracy correlacionou telemetria" in report


def _json(value: dict) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def test_empty_invalid_unknown_and_duplicate_frames_are_temporal_barriers():
    active1 = _correlation(1_000_000, assessment=3)
    active3 = _correlation(3_000_000, assessment=3)
    for kind in ("empty", "invalid", "unknown"):
        barrier = _correlation(2_000_000, assessment=3)
        if kind == "empty": barrier["relations"] = []
        if kind == "invalid": barrier["valid"] = False
        if kind == "unknown": barrier["relations"][0]["id"] = "unknown_mode"
        mode = summarize_electromechanical([active1, barrier, active3])["modes"][0]
        assert mode["max_consecutive_frames"] == 1
        assert mode["persistent"] is False
    mode = summarize_electromechanical([active1, dict(active1)])["modes"][0]
    assert mode["persistent"] is False
    final = _correlation(4_000_000, assessment=3)
    final["relations"] = []
    mode = summarize_electromechanical([active1, active3, final])["modes"][0]
    assert mode["active_now"] is False


def test_legacy_rpm_default_zero_cannot_activate_rotor_lock():
    frame=_correlation(1_000_000,assessment=3)
    del frame['closure']['motor']['rpm_observation_valid']
    assert summarize_electromechanical([frame])['modes']==[]
    frame['relations'][0]['id']='motor_nominal_overload_hypothesis'
    frame['relations'][0]['observed']=100
    frame['relations'][0]['reference']=800
    assert summarize_electromechanical([frame])['modes']==[]
    frame['relations'][0]['observed']=900
    assert summarize_electromechanical([frame])['modes'][0]['active_now'] is True
