import json

from cous.bootstrap import ApiBootstrapResult, bootstrap_auth, upsert_env_value
from cous.config import AuthConfig, Config, OpenTracyConfig
from cous.logger import EventLogger


def test_upsert_env_value_adds_and_replaces_key(tmp_path):
    env_file = tmp_path / ".env"

    changed = upsert_env_value(env_file, "OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "abc")
    changed_again = upsert_env_value(env_file, "OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "def")

    assert changed is True
    assert changed_again is True
    assert env_file.read_text(encoding="utf-8") == 'OPENTRACY_KNOWLEDGE_AUTH_TOKEN="def"\n'


def test_bootstrap_auth_creates_token_and_updates_opentracy_env(tmp_path):
    token_file = tmp_path / "token"
    api_token_file = tmp_path / "api_token"
    env_file = tmp_path / "OpenTracy" / ".env"
    config = Config(
        auth=AuthConfig(
            token_file=str(token_file),
            api_token_file=str(api_token_file),
            opentracy_env_file=str(env_file),
            env_var="COUS_TEST_TOKEN",
        ),
        opentracy=OpenTracyConfig(agent_id="cous"),
    )

    from cous import bootstrap as bootstrap_module

    original = bootstrap_module._ensure_api_channel
    bootstrap_module._ensure_api_channel = lambda cfg: ApiBootstrapResult(
        token="ot_test_token",
        agent_created=True,
        api_connected=True,
        public_url="http://localhost:8001/api/cous/chat",
    )
    try:
        result = bootstrap_auth(config)
    finally:
        bootstrap_module._ensure_api_channel = original

    token = token_file.read_text(encoding="utf-8").strip()
    api_token = api_token_file.read_text(encoding="utf-8").strip()
    assert result.token_created is True
    assert result.api_token_created is True
    assert result.agent_created is True
    assert result.api_connected is True
    assert result.env_updated is True
    assert len(token) >= 32
    assert api_token == "ot_test_token"
    assert env_file.read_text(encoding="utf-8") == (
        f'OPENTRACY_KNOWLEDGE_AUTH_TOKEN="{token}"\n\n'
        f'OPENTRACY_MEASUREMENTS_AUTH_TOKEN="{token}"\n'
    )


def test_event_logger_writes_jsonl(tmp_path):
    logger = EventLogger(tmp_path / "events.jsonl")

    logger.log("chat_user", session_id="chat_1", text="ola")

    line = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["event"] == "chat_user"
    assert payload["session_id"] == "chat_1"
    assert payload["text"] == "ola"


def test_bootstrap_auth_rotates_api_token_when_runtime_is_connected_but_local_file_is_missing(tmp_path):
    token_file = tmp_path / "token"
    env_file = tmp_path / "OpenTracy" / ".env"
    config = Config(
        auth=AuthConfig(
            token_file=str(token_file),
            api_token_file=str(tmp_path / "missing_api_token"),
            opentracy_env_file=str(env_file),
            env_var="COUS_TEST_TOKEN",
        ),
        opentracy=OpenTracyConfig(agent_id="cous"),
    )

    from cous import bootstrap as bootstrap_module

    original = bootstrap_module._ensure_api_channel
    bootstrap_module._ensure_api_channel = lambda cfg: ApiBootstrapResult(
        token="ot_rotated_token",
        agent_created=False,
        api_connected=True,
        public_url="http://localhost:8001/api/cous/chat",
    )
    try:
        result = bootstrap_auth(config)
    finally:
        bootstrap_module._ensure_api_channel = original

    assert result.api_token_created is True
    assert result.api_token_file.read_text(encoding="utf-8").strip() == "ot_rotated_token"
