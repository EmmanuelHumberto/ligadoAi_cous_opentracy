"""Cache for agent system prompt with TTL and local snapshot fallback."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class SystemPromptCache:
    """Cache the agent system prompt from GET /agent/config with TTL.

    Falls back to a local snapshot when the runtime is unavailable.
    """

    def __init__(
        self,
        *,
        client: Any,  # OpenTracyClient — avoids circular import
        config: Any,  # SystemPromptConfig
    ) -> None:
        self._client = client
        self._config = config
        self._cached: str = ""
        self._cached_version: str = ""
        self._last_fetch: float = 0.0
        self._snapshot_path = Path(config.snapshot_file)

    def get(self) -> str:
        now = time.monotonic()
        if self._cached and (now - self._last_fetch) < self._config.cache_ttl_seconds:
            return self._cached

        try:
            agent_config = self._client.get_agent_config()
        except Exception:
            return self._fallback_snapshot()

        system_prompt = agent_config.get("system_prompt", {})
        content = str(system_prompt.get("content") or "")
        version = str(system_prompt.get("version") or "")

        if content:
            self._cached = content
            self._cached_version = version
            self._last_fetch = now
            self._save_snapshot(content)
            return content

        return self._fallback_snapshot()

    def _save_snapshot(self, content: str) -> None:
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._snapshot_path.write_text(content, encoding="utf-8")
        except OSError:
            pass  # snapshot é otimização, não bloqueia

    def _fallback_snapshot(self) -> str:
        if self._snapshot_path.is_file():
            try:
                return self._snapshot_path.read_text(encoding="utf-8")
            except OSError:
                pass
        if self._cached:
            return self._cached
        return (
            "You are Cous, a specialized technical assistant for tattoo machine "
            "analysis and diagnostics. Respond in Portuguese."
        )
