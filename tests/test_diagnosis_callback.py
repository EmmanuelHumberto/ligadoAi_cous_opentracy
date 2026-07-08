"""Tests for OpenTracy diagnosis callbacks received by Cous."""

from uuid import UUID

import httpx
import pytest

from cous.callback_server import create_callback_app, start_background_callback_server
from cous.clients.diagnosis import DiagnosisCallbackHandler
from cous.config import Config, MeasurementsConfig
from cous.contracts.v3_schemas import DiagnosisCallbackPayload
from cous.measurements.store import MeasurementLocalStore

CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000001")
CAPTURE_SESSION_ID = UUID("00000000-0000-0000-0000-000000000002")
TRACE_ID = UUID("00000000-0000-0000-0000-000000000003")
HYPOTHESIS_ID = UUID("00000000-0000-0000-0000-000000000004")


def test_callback_handler_persists_completed_result(tmp_path):
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    session = store.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "capture_session_id": str(CAPTURE_SESSION_ID),
        }
    )
    session["diagnosis_correlation_id"] = str(CORRELATION_ID)
    store.replace_session(session)
    handler = DiagnosisCallbackHandler(store)

    handler.handle_callback(
        DiagnosisCallbackPayload(
            correlation_id=CORRELATION_ID,
            capture_session_id=CAPTURE_SESSION_ID,
            trace_id=TRACE_ID,
            duration_ms=120,
            hypotheses=[
                {
                    "hypothesis_id": HYPOTHESIS_ID,
                    "description": "Atrito elevado no conjunto rotativo.",
                    "confidence": 0.82,
                    "is_primary": True,
                }
            ],
            explanation={
                "narrative": "Assinatura eletromecanica indica degradacao.",
                "confidence": 0.79,
            },
        )
    )

    updated = store.get_session(session["id"])
    assert updated is not None
    assert updated["diagnosis_status"] == "completed"
    assert updated["diagnosis_result"]["trace_id"] == str(TRACE_ID)
    assert updated["diagnosis_result"]["hypotheses"][0]["is_primary"] is True
    assert "diagnosis_error" not in updated
    assert handler.get_result(CORRELATION_ID) is not None


def test_callback_handler_persists_failed_result_by_capture_session(tmp_path):
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    session = store.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "capture_session_id": str(CAPTURE_SESSION_ID),
        }
    )
    handler = DiagnosisCallbackHandler(store)

    handler.handle_callback(
        DiagnosisCallbackPayload(
            correlation_id=CORRELATION_ID,
            capture_session_id=CAPTURE_SESSION_ID,
            trace_id=TRACE_ID,
            duration_ms=10,
            error="worker failed",
        )
    )

    updated = store.get_session(session["id"])
    assert updated is not None
    assert updated["diagnosis_correlation_id"] == str(CORRELATION_ID)
    assert updated["diagnosis_status"] == "failed"
    assert updated["diagnosis_error"] == "worker failed"
    assert updated["diagnosis_result"]["error"] == "worker failed"


def test_callback_handler_reloads_store_before_matching_session(tmp_path):
    storage_file = tmp_path / "measurements.json"
    writer_store = MeasurementLocalStore(storage_file)
    callback_store = MeasurementLocalStore(storage_file)
    session = writer_store.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
        }
    )
    callback_store.full_sessions()
    session["capture_session_id"] = str(CAPTURE_SESSION_ID)
    session["diagnosis_correlation_id"] = str(CORRELATION_ID)
    writer_store.replace_session(session)
    handler = DiagnosisCallbackHandler(callback_store)

    handler.handle_callback(
        DiagnosisCallbackPayload(
            correlation_id=CORRELATION_ID,
            capture_session_id=CAPTURE_SESSION_ID,
            trace_id=TRACE_ID,
            duration_ms=120,
            hypotheses=[
                {
                    "hypothesis_id": HYPOTHESIS_ID,
                    "description": "Atrito elevado no conjunto rotativo.",
                    "confidence": 0.82,
                    "is_primary": True,
                }
            ],
        )
    )

    writer_store.invalidate_cache()
    updated = writer_store.get_session(session["id"])
    assert updated is not None
    assert updated["diagnosis_status"] == "completed"
    assert updated["diagnosis_result"]["correlation_id"] == str(CORRELATION_ID)


def test_callback_handler_raises_when_session_cannot_be_persisted(tmp_path):
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    handler = DiagnosisCallbackHandler(store)

    with pytest.raises(ValueError, match="Sessao local nao encontrada"):
        handler.handle_callback(
            DiagnosisCallbackPayload(
                correlation_id=CORRELATION_ID,
                capture_session_id=CAPTURE_SESSION_ID,
                trace_id=TRACE_ID,
                duration_ms=120,
                hypotheses=[],
            )
        )


def test_background_callback_uses_alternate_port_when_preferred_is_busy(
    tmp_path,
    monkeypatch,
):
    storage_file = tmp_path / "measurements.json"
    config = Config(measurements=MeasurementsConfig(storage_file=str(storage_file)))
    calls = []

    def fake_can_bind(host, port):
        calls.append((host, port))
        return port == 8010

    class FakeServer:
        should_exit = False

        def __init__(self, _config):
            pass

        def run(self):
            return None

    monkeypatch.setattr("cous.callback_server._can_bind", fake_can_bind)
    monkeypatch.setattr("uvicorn.Server", FakeServer)

    server = start_background_callback_server(config)
    assert server is not None
    server.stop()

    assert ("127.0.0.1", 8000) in calls
    assert server.endpoint == "http://127.0.0.1:8010/cous/diagnosis/callback"
    assert config.opentracy.diagnosis_callback_endpoint == server.endpoint


@pytest.mark.anyio
async def test_callback_http_endpoint_persists_result(tmp_path):
    storage_file = tmp_path / "measurements.json"
    store = MeasurementLocalStore(storage_file)
    session = store.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "capture_session_id": str(CAPTURE_SESSION_ID),
        }
    )
    config = Config(measurements=MeasurementsConfig(storage_file=str(storage_file)))
    transport = httpx.ASGITransport(app=create_callback_app(config))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/cous/diagnosis/callback",
            json={
                "correlation_id": str(CORRELATION_ID),
                "capture_session_id": str(CAPTURE_SESSION_ID),
                "trace_id": str(TRACE_ID),
                "duration_ms": 64,
                "hypotheses": [
                    {
                        "hypothesis_id": str(HYPOTHESIS_ID),
                        "description": "Desgaste no conjunto rotativo.",
                        "confidence": 0.77,
                        "is_primary": True,
                    }
                ],
                "explanation": {
                    "narrative": "Diagnostico gerado pelo worker OpenTracy.",
                    "confidence": 0.73,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "received"

    store.invalidate_cache()
    updated = store.get_session(session["id"])
    assert updated is not None
    assert updated["diagnosis_status"] == "completed"
    assert updated["diagnosis_result"]["correlation_id"] == str(CORRELATION_ID)


@pytest.mark.anyio
async def test_callback_http_endpoint_rejects_unmatched_session(tmp_path):
    storage_file = tmp_path / "measurements.json"
    config = Config(measurements=MeasurementsConfig(storage_file=str(storage_file)))
    transport = httpx.ASGITransport(app=create_callback_app(config))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/cous/diagnosis/callback",
            json={
                "correlation_id": str(CORRELATION_ID),
                "capture_session_id": str(CAPTURE_SESSION_ID),
                "trace_id": str(TRACE_ID),
                "duration_ms": 64,
                "hypotheses": [],
            },
        )

    assert response.status_code == 409
    assert "Sessao local nao encontrada" in response.text
