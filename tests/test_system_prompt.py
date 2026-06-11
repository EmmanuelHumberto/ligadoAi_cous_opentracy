"""Testes para o cache de system prompt."""

import tempfile
from pathlib import Path

import pytest

from cous.clients.system_prompt import SystemPromptCache


class FakeConfig:
    def __init__(self, cache_ttl_seconds, snapshot_file):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.snapshot_file = snapshot_file


class FakeClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.call_count = 0

    def get_agent_config(self):
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response or {}


class TestSystemPromptCache:

    @pytest.fixture
    def tmp_snapshot(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("snapshot content")
            path = Path(f.name)
        yield path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    # ── Cache hit / miss ────────────────────────────────────────────────

    def test_cache_hit_within_ttl(self, tmp_path):
        client = FakeClient(response={
            "system_prompt": {"content": "You are Cous.", "version": "v1"}
        })
        snap = tmp_path / "snap.md"
        config = FakeConfig(cache_ttl_seconds=300, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        r1 = cache.get()
        assert r1 == "You are Cous."
        assert client.call_count == 1

        r2 = cache.get()
        assert r2 == "You are Cous."
        assert client.call_count == 1

    def test_cache_miss_expired_ttl(self, tmp_path):
        client = FakeClient(response={
            "system_prompt": {"content": "fresh", "version": "v2"}
        })
        snap = tmp_path / "snap.md"
        config = FakeConfig(cache_ttl_seconds=0, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        cache.get()
        assert client.call_count == 1
        cache.get()
        assert client.call_count == 2

    # ── Fallbacks ───────────────────────────────────────────────────────

    def test_fallback_snapshot_when_client_fails(self, tmp_snapshot):
        client = FakeClient(error=RuntimeError("down"))
        config = FakeConfig(cache_ttl_seconds=300, snapshot_file=str(tmp_snapshot))
        cache = SystemPromptCache(client=client, config=config)

        assert cache.get() == "snapshot content"

    def test_fallback_cached_when_no_snapshot(self, tmp_path):
        client = FakeClient(response={
            "system_prompt": {"content": "cached prompt", "version": "v1"}
        })
        snap = tmp_path / "snap.md"
        config = FakeConfig(cache_ttl_seconds=0, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        cache.get()
        client._error = RuntimeError("down")
        assert cache.get() == "cached prompt"

    def test_default_fallback_when_everything_fails(self, tmp_path):
        client = FakeClient(error=RuntimeError("down"))
        snap = tmp_path / "nonexistent.md"
        config = FakeConfig(cache_ttl_seconds=0, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        result = cache.get()
        assert "Cous" in result
        assert "Portuguese" in result

    def test_empty_content_falls_back(self, tmp_path):
        client = FakeClient(response={
            "system_prompt": {"content": "", "version": ""}
        })
        snap = tmp_path / "nonexistent.md"
        config = FakeConfig(cache_ttl_seconds=0, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        result = cache.get()
        assert "Cous" in result

    def test_snapshot_saved_on_successful_fetch(self, tmp_path):
        client = FakeClient(response={
            "system_prompt": {"content": "new prompt", "version": "v2"}
        })
        snap = tmp_path / "snap.md"
        config = FakeConfig(cache_ttl_seconds=0, snapshot_file=str(snap))
        cache = SystemPromptCache(client=client, config=config)

        cache.get()
        assert snap.is_file()
        assert snap.read_text() == "new prompt"
