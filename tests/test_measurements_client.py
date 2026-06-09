import pytest

from cous.auth import TokenProvider
from cous.clients.measurements import MeasurementsClient
from cous.config import OpenTracyConfig
from cous.measurements.store import MeasurementLocalStore


def _client(tmp_path, monkeypatch) -> MeasurementsClient:
    monkeypatch.setenv("TEST_MEASUREMENTS_TOKEN", "token")
    return MeasurementsClient(
        OpenTracyConfig(),
        TokenProvider("unused", "TEST_MEASUREMENTS_TOKEN"),
        MeasurementLocalStore(tmp_path / "measurements.json"),
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
            {"type": "power_snapshot", "timestamp_us": 2, "bus_voltage_mv": 8000, "current_ma": -80},
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
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    client.add_snapshots(
        session["id"],
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )

    resolved = client.get_session(session["id"][:16])
    summary = client.recent_summary()

    assert resolved["id"] == session["id"]
    assert "Medicoes recentes:" in summary
    assert "freq_media=120.00Hz" in summary


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
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
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
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_post(url: str, payload: dict):
        calls.append(("POST", url, payload))
        if url.endswith("/measurements/sessions"):
            return {"id": "00000000-0000-0000-0000-000000000123"}
        return {"accepted": 1, "rejected": 0}

    monkeypatch.setattr(client._http, "post", fake_post)

    synced = client.sync_session(session["id"])

    assert synced["sync_status"] == "synced"
    assert synced["remote_id"] == "00000000-0000-0000-0000-000000000123"
    assert len(calls) == 2


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
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
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
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
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
