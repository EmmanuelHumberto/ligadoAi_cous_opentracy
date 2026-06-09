from cous.config import OpenTracyConfig


def test_opentracy_config_normalizes_localhost_loopback():
    config = OpenTracyConfig(
        backend_url="http://localhost:8002",
        runtime_url="http://localhost:8001",
    )

    assert config.backend_url == "http://127.0.0.1:8002"
    assert config.runtime_url == "http://127.0.0.1:8001"
