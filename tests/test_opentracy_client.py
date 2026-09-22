from cous.clients.opentracy import OpenTracyClient
from cous.config import OpenTracyConfig


def test_chat_uses_dedicated_read_timeout():
    calls = []

    class FakeHttp:
        def post(self, url, payload, *, timeout=None):
            calls.append((url, payload, timeout))
            return {"response": "ok"}

    client = object.__new__(OpenTracyClient)
    client._config = OpenTracyConfig(agent_id="_default", chat_timeout=120)
    client._backend_url = "http://127.0.0.1:8002"
    client._auth = FakeHttp()

    result = client.chat("consulta")

    assert result == {"response": "ok"}
    assert calls == [
        (
            "http://127.0.0.1:8002/v1/api/_default/chat",
            {"request": "consulta", "channel": "terminal"},
            120,
        )
    ]
