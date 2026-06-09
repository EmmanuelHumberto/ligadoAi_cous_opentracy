from cous.bootstrap import bootstrap_auth, upsert_env_value
from cous.config import AuthConfig


def test_upsert_env_value_adds_and_replaces_key(tmp_path):
    env_file = tmp_path / ".env"

    changed = upsert_env_value(env_file, "OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "abc")
    changed_again = upsert_env_value(env_file, "OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "def")

    assert changed is True
    assert changed_again is True
    assert env_file.read_text(encoding="utf-8") == 'OPENTRACY_KNOWLEDGE_AUTH_TOKEN="def"\n'


def test_bootstrap_auth_creates_token_and_updates_opentracy_env(tmp_path):
    token_file = tmp_path / "token"
    env_file = tmp_path / "OpenTracy" / ".env"
    config = AuthConfig(
        token_file=str(token_file),
        opentracy_env_file=str(env_file),
        env_var="COUS_TEST_TOKEN",
    )

    result = bootstrap_auth(config)

    token = token_file.read_text(encoding="utf-8").strip()
    assert result.token_created is True
    assert result.env_updated is True
    assert len(token) >= 32
    assert env_file.read_text(encoding="utf-8") == f'OPENTRACY_KNOWLEDGE_AUTH_TOKEN="{token}"\n'
