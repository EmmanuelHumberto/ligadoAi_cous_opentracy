from pathlib import Path

import pytest

from cous.auth import AuthError, TokenProvider, load_token_file, save_token_file
from cous.config import AuthConfig


def test_token_provider_prefers_env(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    save_token_file("file-token", str(token_file))
    monkeypatch.setenv("COUS_TOKEN_TEST", "env-token")

    provider = TokenProvider(str(token_file), "COUS_TOKEN_TEST")

    assert provider.load() == "env-token"


def test_named_token_providers_use_distinct_files(tmp_path):
    knowledge_token = tmp_path / "knowledge"
    api_token = tmp_path / "api"
    save_token_file("knowledge-token", str(knowledge_token))
    save_token_file("api-token", str(api_token))
    config = AuthConfig(
        token_file=str(knowledge_token),
        api_token_file=str(api_token),
    )

    assert TokenProvider.for_knowledge(config).load() == "knowledge-token"
    assert TokenProvider.for_api(config).load() == "api-token"


def test_save_and_load_token_file(tmp_path):
    token_file = tmp_path / "token"

    saved = save_token_file("abc", str(token_file))

    assert saved == Path(token_file)
    assert load_token_file(str(token_file)) == "abc"


def test_missing_token_file_fails(tmp_path):
    with pytest.raises(AuthError):
        load_token_file(str(tmp_path / "missing"))
