import json

import httpx

from cous.clients.systemos import SystemOsTelemetryClient
from cous.config import SystemOsConfig


def test_systemos_sends_frames_in_idempotent_batches(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"id": f"lot-{len(requests)}"})

    monkeypatch.setenv("TEST_SYSTEMOS_KEY", "secret")
    client = SystemOsTelemetryClient(
        SystemOsConfig(
            enabled=True,
            base_url="http://systemos.test/api/v1",
            organization_id="58e2d7a9-18b1-48b9-9dc6-4c931779a80c",
            api_key_env_var="TEST_SYSTEMOS_KEY",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    frames = [
        {
            "type": "hall_snapshot",
            "version": 1,
            "timestamp_us": index + 1,
            "valid": True,
        }
        for index in range(120)
    ]

    receipt = client.sync_session(
        {
            "id": "med_test",
            "created_at": "2026-09-25T01:05:30.216598+00:00",
            "header": {
                "ordem_servico": "OS-1132",
                "numero_serie": "SN-1",
                "porta_serial": "/dev/ttyACM0",
                "tipo_coleta": "pos-reparo",
                "observacoes": "Teste final apos manutencao",
            },
            "snapshots": frames,
        }
    )

    assert receipt["batch_count"] == 3
    assert receipt["frame_count"] == 120
    payloads = [json.loads(request.content) for request in requests]
    assert [len(payload["frames"]) for payload in payloads] == [50, 50, 20]
    assert [payload["chaveIdempotencia"] for payload in payloads] == [
        "cous:med_test:0000",
        "cous:med_test:0001",
        "cous:med_test:0002",
    ]
    assert all(request.headers["x-tdma-key"] == "secret" for request in requests)
    assert all(
        payload["recebidoEm"] == "2026-09-25T01:05:30.216598+00:00" for payload in payloads
    )
    assert all(payload["tipoColeta"] == "pos-reparo" for payload in payloads)
    assert all(
        payload["observacoesColeta"] == "Teste final apos manutencao" for payload in payloads
    )
