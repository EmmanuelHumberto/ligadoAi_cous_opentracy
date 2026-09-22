import pytest

from cous.auth import TokenProvider
from cous.clients.measurements import MeasurementsClient
from cous.config import OpenTracyConfig
from cous.measurements.store import MeasurementLocalStore


class ContractMeasurementsClient(MeasurementsClient):
    def create_session(self, header):
        return super().create_session(
            {
                "ordem_servico": "OS-TEST",
                "numero_serie": "SN-TEST",
                **header,
            }
        )


def _client(tmp_path, monkeypatch) -> MeasurementsClient:
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    return ContractMeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )


def test_evidence_excludes_unavailable_mechanical_model(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    evidence = client._build_evidence_data(
        "electromechanical_signature",
        [
            {
                "type": "electromechanical_signature",
                "bus_voltage_mv": 6000,
                "current_ma": 70,
                "rpm_mpu": 5500,
                "required_torque_uNm": 2462,
                "mechanical_equivalent_load_permille": 5400,
                "required_mechanical_power_mw": 1594,
                "cartridge_compression_um": 3500,
            }
        ],
    )

    assert evidence["bus_voltage_mv_avg"] == 6000
    assert evidence["current_ma_avg"] == 70
    assert evidence["rpm_mpu_avg"] == 5500
    assert "required_torque_uNm_avg" not in evidence
    assert "mechanical_equivalent_load_permille_avg" not in evidence
    assert "required_mechanical_power_mw_avg" not in evidence
    assert "cartridge_compression_um_avg" not in evidence


def test_create_session_requires_service_order_and_serial(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = MeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )

    with pytest.raises(ValueError, match="ordem_servico.*numero_serie"):
        client.create_session(
            {
                "tipo_coleta": "desempenho",
                "verticais": ["hall"],
            }
        )


def test_create_session_requires_peca_substituida_for_repair(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="peca_substituida"):
        client.create_session(
            {
                "tipo_coleta": "reparo",
                "verticais": ["hall"],
                "baudrate": 115200,
                "duracao_seg": 30.0,
            }
        )


def test_client_persists_and_lists_local_sessions(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    session = client.create_session(
        {
            "fabricante": "FK Irons",
            "modelo": "Flux",
            "tipo_coleta": "desempenho",
            "verticais": ["hall", "power"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    result = client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "rpm": 120},
            {"type": "unknown", "timestamp_us": 2},
        ],
    )

    sessions = client.list_sessions()
    stored = client.get_session(session["id"])

    assert len(sessions) == 1
    assert result["accepted"] == 1
    assert result["rejected"] == 1
    assert stored["valid_snapshots"] == 1
    assert stored["invalid_snapshots"] == 1
    assert stored["snapshots_by_type"] == {"hall": 1}


def test_client_filters_sessions_and_generates_local_report(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "numero_serie": "1199",
            "tipo_coleta": "desempenho",
            "verticais": ["hall", "power"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120, "rpm_inferred": 7200},
            {
                "type": "power_snapshot",
                "timestamp_us": 2,
                "bus_voltage_mv": 8000,
                "current_ma": -80,
            },
        ],
    )

    filtered = client.list_sessions("W1PRO")
    report = client.report(session["id"])
    context = client.chat_context("dados da W1PRO")

    assert len(filtered) == 1
    assert "Laudo Local" in report["markdown"]
    assert "W1PRO" in report["markdown"]
    assert "freq_media=120.00Hz" in context


def test_client_resolves_prefix_and_recent_summary(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall", "signature"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
            {
                "type": "electromechanical_signature",
                "timestamp_us": 3,
                "efficiency_permille": 0,
                "efficiency_valid": False,
                "mechanical_power_mw": 0,
                "mechanical_power_valid": False,
            },
            {
                "type": "electromechanical_signature",
                "timestamp_us": 4,
                "efficiency_permille": 610,
                "efficiency_valid": True,
                "mechanical_power_mw": 540,
                "mechanical_power_valid": True,
            },
        ],
    )

    resolved = client.get_session(session["id"][:16])
    summary = client.recent_summary()

    assert resolved["id"] == session["id"]
    assert "Medicoes recentes:" in summary
    assert "freq_media=121.00Hz" in summary


def test_chat_context_uses_recent_sessions_for_generic_measurement_query(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "numero_serie": "1199",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
            {
                "type": "electromechanical_signature",
                "timestamp_us": 3,
                "efficiency_permille": 0,
                "efficiency_valid": False,
                "mechanical_power_mw": 0,
                "mechanical_power_valid": False,
            },
            {
                "type": "electromechanical_signature",
                "timestamp_us": 4,
                "efficiency_permille": 610,
                "efficiency_valid": True,
                "mechanical_power_mw": 540,
                "mechanical_power_valid": True,
            },
        ],
    )

    context = client.chat_context("voce consegue achar a coleta salva?")

    assert session["id"] in context
    assert "DKLAB" in context


def test_client_syncs_session_to_runtime(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
        ],
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_post(url: str, payload: dict):
        calls.append(("POST", url, payload))
        if url.endswith("/measurements/sessions"):
            return {"id": "00000000-0000-0000-0000-000000000123"}
        return {"accepted": 2, "rejected": 0, "duplicates": 0}

    monkeypatch.setattr(client._http, "post", fake_post)

    synced = client.sync_session(session["id"])

    assert synced["sync_status"] == "synced"
    assert synced["remote_id"] == "00000000-0000-0000-0000-000000000123"
    assert synced["sync_receipt"] == {
        "accepted": 2,
        "rejected": 0,
        "duplicates": 0,
    }
    assert all(
        snapshot["event_id"].startswith(f"tma:{session['id']}:")
        for snapshot in calls[1][2]["snapshots"]
    )
    assert calls[0][2]["header"]["source_session_id"] == session["id"]
    assert len(calls) == 2


def test_client_does_not_mark_rejected_snapshots_as_synced(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )

    def fake_post(url: str, payload: dict):
        if url.endswith("/measurements/sessions"):
            return {"id": "00000000-0000-0000-0000-000000000123"}
        return {
            "accepted": 0,
            "rejected": 1,
            "duplicates": 0,
            "errors": [{"code": "invalid_contract"}],
        }

    monkeypatch.setattr(client._http, "post", fake_post)

    try:
        client.sync_session(session["id"])
    except RuntimeError as exc:
        assert "rejected 1" in str(exc)
    else:
        raise AssertionError("sync_session should fail when OpenTracy rejects data")

    failed = client.get_session(session["id"])
    assert failed["sync_status"] == "sync_failed"
    assert "invalid_contract" in failed["last_sync_error"]


def test_client_report_prefers_remote_and_updates_local_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
        ],
    )
    synced = client.get_session(session["id"])
    synced["remote_id"] = "00000000-0000-0000-0000-000000000123"
    synced["sync_status"] = "synced"
    client._store.replace_session(synced)

    def fake_post(url: str, payload: dict):
        assert url.endswith("/measurements/sessions/00000000-0000-0000-0000-000000000123/report")
        return {
            "markdown": "# remoto",
            "session": {
                "id": "00000000-0000-0000-0000-000000000123",
                "status": "reported",
                "total_snapshots": 1,
                "valid_snapshots": 1,
                "invalid_snapshots": 0,
                "diagnostic": {"approved": True, "summary": "ok"},
                "report_markdown": "# remoto",
            },
        }

    monkeypatch.setattr(client._http, "post", fake_post)

    result = client.report(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "remote"
    assert stored["status"] == "reported"
    assert stored["report_markdown"] == "# remoto"


def test_client_diagnose_falls_back_to_local_when_remote_fails(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
        ],
    )

    def fake_sync(session_id: str):
        current = client.get_session(session_id)
        current["remote_id"] = "00000000-0000-0000-0000-000000000123"
        current["sync_status"] = "synced"
        return client._store.replace_session(current)

    def fake_post(url: str, payload: dict):
        raise RuntimeError("runtime offline")

    monkeypatch.setattr(client, "sync_session", fake_sync)
    monkeypatch.setattr(client._http, "post", fake_post)

    result = client.diagnose(session["id"])

    assert result["source"] == "local"
    assert result["diagnostic"]["approved"] is True


def test_diagnose_v3_requires_real_identity_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
        ],
    )

    result = client.diagnose_v3(session["id"])

    assert result["source"] == "v3-local-fallback"
    assert result["diagnostic"]["status"] == "measurement_only"
    assert result["diagnostic"]["queue_status"] == "local_fallback"
    assert "capture_session_id" in result["diagnostic"]["error"]
    assert "instance_id" in result["diagnostic"]["error"]
    assert "domain_id" in result["diagnostic"]["error"]


def test_diagnose_v3_sends_payload_with_configured_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(
            diagnosis_domain_id="00000000-0000-0000-0000-0000000000d1",
            diagnosis_instance_id="00000000-0000-0000-0000-0000000000a1",
        ),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall", "signature"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
            "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
        }
    )
    client.add_snapshots(
        session["id"],
        [
            {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120},
            {"type": "hall_snapshot", "timestamp_us": 2, "frequency_hz": 122},
            {
                "type": "electromechanical_signature",
                "timestamp_us": 3,
                "efficiency_permille": 0,
                "efficiency_valid": False,
                "mechanical_power_mw": 0,
                "mechanical_power_valid": False,
            },
            {
                "type": "electromechanical_signature",
                "timestamp_us": 4,
                "efficiency_permille": 610,
                "efficiency_valid": True,
                "mechanical_power_mw": 540,
                "mechanical_power_valid": True,
            },
        ],
    )
    sent = {}
    projected = {}

    def fake_projection(current, capture_session_id):
        projected["capture_session_id"] = str(capture_session_id)
        current["capture_projection_status"] = "projected"
        return client._store.replace_session(current)

    def fake_request(self, payload):
        sent["payload"] = payload
        return {"status": "queued"}

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.request_diagnosis",
        fake_request,
    )
    monkeypatch.setattr(client, "_synchronize_capture_projection", fake_projection)

    result = client.diagnose_v3(session["id"])

    assert result["source"] == "v3-remote"
    assert result["diagnostic"]["status"] == "queued"
    stored = client.get_session(session["id"])
    assert "diagnosis_error" not in stored
    assert "diagnosis_v3_error" not in stored
    assert (
        str(sent["payload"].capture_session_id)
        == "00000000-0000-0000-0000-0000000000c1"
    )
    hall_evidence = next(
        item for item in sent["payload"].evidence_set if item.data["type"] == "hall_snapshot"
    )
    assert hall_evidence.data["frequency_hz_avg"] == 121
    assert hall_evidence.data["frequency_hz_min"] == 120
    assert hall_evidence.data["frequency_hz_max"] == 122
    signature_evidence = next(
        item
        for item in sent["payload"].evidence_set
        if item.data["type"] == "electromechanical_signature"
    )
    assert signature_evidence.data["efficiency_permille_avg"] == 610
    assert signature_evidence.data["mechanical_power_mw_avg"] == 540
    service_order_evidence = next(
        item
        for item in sent["payload"].evidence_set
        if item.evidence_type == "service_order_context"
    )
    assert service_order_evidence.data["service_order_number"] == "OS-TEST"
    assert service_order_evidence.data["equipment_serial_number"] == "SN-TEST"
    assert sent["payload"].context.service_order_number == "OS-TEST"
    assert (
        str(sent["payload"].instance_id)
        == "00000000-0000-0000-0000-0000000000a1"
    )
    assert str(sent["payload"].domain_id) == "00000000-0000-0000-0000-0000000000d1"
    assert projected["capture_session_id"] == "00000000-0000-0000-0000-0000000000c1"


def test_diagnose_v3_accepts_measurement_without_service_order(tmp_path, monkeypatch):
    """Medições antigas (pré-validação) sem ordem_servico não devem quebrar o payload."""
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(
            diagnosis_domain_id="00000000-0000-0000-0000-0000000000d1",
            diagnosis_instance_id="00000000-0000-0000-0000-0000000000a1",
        ),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "EZ",
            "modelo": "P2S",
            "numero_serie": "P2S-072301180",
            "ordem_servico": "1120",
            "observacoes": "os 1120",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
            "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
        }
    )
    client.add_snapshots(
        session["id"],
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )

    # Simula medição antiga capturada antes de ordem_servico ser obrigatória
    stored = client.get_session(session["id"])
    stored["header"].pop("ordem_servico", None)
    client._store.replace_session(stored)

    sent = {}

    def fake_projection(current, capture_session_id):
        current["capture_projection_status"] = "projected"
        return client._store.replace_session(current)

    def fake_request(self, payload):
        sent["payload"] = payload
        return {"status": "queued"}

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.request_diagnosis",
        fake_request,
    )
    monkeypatch.setattr(client, "_synchronize_capture_projection", fake_projection)

    result = client.diagnose_v3(session["id"])

    assert result["source"] == "v3-remote"
    assert sent["payload"].context.service_order_number is None
    assert sent["payload"].context.reported_problem == "os 1120"
    assert sent["payload"].context.equipment_serial_number == "P2S-072301180"
    service_order_evidence = next(
        item
        for item in sent["payload"].evidence_set
        if item.evidence_type == "service_order_context"
    )
    assert service_order_evidence.data["service_order_number"] is None
    assert service_order_evidence.data["observations"] == "os 1120"


def test_diagnose_v3_auto_resolves_identity_before_sending(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(diagnosis_auto_resolve_identity=True),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "numero_serie": "1199",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
            "tecnico": "ana",
        }
    )
    client.add_snapshots(
        session["id"],
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )

    def fake_post(url: str, payload: dict):
        assert url.endswith("/v3/operational/resolve-capture")
        assert payload["manufacturer"] == "DKLAB"
        assert payload["model"] == "W1PRO"
        assert payload["serial_number"] == "1199"
        assert payload["service_order_number"] == "OS-TEST"
        assert payload["operator_name"] == "ana"
        return {
            "domain_id": "00000000-0000-0000-0000-0000000000d1",
            "entity_id": "00000000-0000-0000-0000-0000000000e1",
            "instance_id": "00000000-0000-0000-0000-0000000000a1",
            "operational_session_id": "00000000-0000-0000-0000-0000000000b1",
            "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
            "service_order_document_id": "00000000-0000-0000-0000-0000000000f1",
        }

    sent = {}

    def fake_request(self, payload):
        sent["payload"] = payload
        return {"status": "queued"}

    monkeypatch.setattr(client._http, "post", fake_post)
    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.request_diagnosis",
        fake_request,
    )

    result = client.diagnose_v3(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "v3-remote"
    assert stored["capture_session_id"] == "00000000-0000-0000-0000-0000000000c1"
    assert (
        stored["service_order_document_id"]
        == "00000000-0000-0000-0000-0000000000f1"
    )
    assert str(sent["payload"].capture_session_id) == stored["capture_session_id"]
    assert str(sent["payload"].instance_id) == stored["instance_id"]
    assert str(sent["payload"].domain_id) == stored["domain_id"]


def test_refresh_diagnosis_status_updates_local_session(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_correlation_id"] = "00000000-0000-0000-0000-0000000000d9"
    session["diagnosis_status"] = "queued"
    client._store.replace_session(session)

    def fake_status(self, correlation_id):
        assert str(correlation_id) == "00000000-0000-0000-0000-0000000000d9"
        return {
            "correlation_id": str(correlation_id),
            "status": "processing",
            "attempts": 2,
            "last_attempt_at": "2026-07-07T12:00:00+00:00",
            "callback_status": "pending",
            "callback_attempts": 1,
            "callback_error": "connection refused",
        }

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.diagnosis_status",
        fake_status,
    )

    result = client.refresh_diagnosis_status(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "v3-remote"
    assert stored["diagnosis_status"] == "processing"
    assert stored["diagnosis_attempts"] == 2
    assert stored["diagnosis_last_attempt_at"] == "2026-07-07T12:00:00+00:00"
    assert stored["diagnosis_callback_status"] == "pending"
    assert stored["diagnosis_callback_attempts"] == 1
    assert stored["diagnosis_callback_error"] == "connection refused"


def test_refresh_diagnosis_status_preserves_queued_on_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_correlation_id"] = "00000000-0000-0000-0000-0000000000d9"
    session["diagnosis_status"] = "queued"
    client._store.replace_session(session)

    def fake_status(self, correlation_id):
        return {
            "correlation_id": str(correlation_id),
            "status": "unknown",
        }

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.diagnosis_status",
        fake_status,
    )

    result = client.refresh_diagnosis_status(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "v3-remote"
    assert stored["diagnosis_status"] == "queued"


def test_refresh_diagnosis_status_waits_for_callback_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_correlation_id"] = "00000000-0000-0000-0000-0000000000d9"
    session["diagnosis_status"] = "queued"
    client._store.replace_session(session)

    def fake_status(self, correlation_id):
        return {
            "correlation_id": str(correlation_id),
            "status": "completed",
            "attempts": 1,
        }

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.diagnosis_status",
        fake_status,
    )

    result = client.refresh_diagnosis_status(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "v3-remote"
    assert stored["diagnosis_status"] == "awaiting_callback"


def test_refresh_diagnosis_status_persists_remote_result_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    client = ContractMeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
    )
    session = client.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_correlation_id"] = "00000000-0000-0000-0000-0000000000d9"
    session["diagnosis_status"] = "queued"
    client._store.replace_session(session)

    def fake_status(self, correlation_id):
        return {
            "correlation_id": str(correlation_id),
            "status": "completed",
            "attempts": 1,
            "result": {
                "correlation_id": str(correlation_id),
                "hypotheses": [
                    {
                        "description": "Atrito elevado",
                        "confidence": 0.82,
                        "is_primary": True,
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "cous.clients.diagnosis.DiagnosisClient.diagnosis_status",
        fake_status,
    )

    result = client.refresh_diagnosis_status(session["id"])
    stored = client.get_session(session["id"])

    assert result["source"] == "v3-remote"
    assert stored["diagnosis_status"] == "completed"
    assert stored["diagnosis_result"]["hypotheses"][0]["description"] == "Atrito elevado"


def test_diagnosis_runtime_status_uses_runtime_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    requested = {}

    def fake_get(self, url):
        requested["url"] = url
        return {
            "status": "available",
            "database_configured": True,
            "worker_enabled": True,
            "worker_running": True,
        }

    monkeypatch.setattr("cous.clients.base.AuthenticatedHttpClient.get", fake_get)

    result = client.diagnosis_runtime_status()

    assert requested["url"].endswith("/v3/diagnosis/status")
    assert result["status"] == "available"
    assert result["worker_running"] is True
