from cous.config import OpenTracyConfig, SystemOsConfig


def test_opentracy_config_normalizes_localhost_loopback():
    config = OpenTracyConfig(
        backend_url="http://localhost:8002",
        runtime_url="http://localhost:8001",
    )

    assert config.backend_url == "http://127.0.0.1:8002"
    assert config.runtime_url == "http://127.0.0.1:8001"
    assert config.timeout == 30
    assert config.chat_timeout == 120


def test_systemos_config_normalizes_url_and_timeout():
    config = SystemOsConfig(base_url="http://localhost:3001/api/v1/", timeout=0)

    assert config.base_url == "http://127.0.0.1:3001/api/v1"
    assert config.timeout == 30
