"""Client for OpenTracy chat/runtime endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from cous.auth import TokenProvider
from cous.clients.base import AuthenticatedHttpClient, ClientError
from cous.config import OpenTracyConfig


class OpenTracyClient:
    def __init__(self, config: OpenTracyConfig, token_provider: TokenProvider) -> None:
        self._config = config
        self._auth = AuthenticatedHttpClient(
            token_provider=token_provider,
            timeout=config.timeout,
        )
        self._plain = httpx.Client(timeout=httpx.Timeout(config.timeout))
        self._backend_url = config.backend_url.rstrip("/")
        self._runtime_url = config.runtime_url.rstrip("/")

    def health(self) -> dict[str, bool]:
        return {
            "backend": self._is_healthy(f"{self._backend_url}/health"),
            "runtime": self._is_healthy(f"{self._runtime_url}/health"),
        }

    def chat(
        self,
        request: str,
        *,
        history: list[dict[str, str]] | None = None,
        channel: str = "terminal",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"request": request, "channel": channel}
        if history:
            payload["history"] = history
        if session_id:
            payload["session_id"] = session_id
        return self._auth.post(
            f"{self._backend_url}/v1/api/{self._config.agent_id}/chat",
            payload,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        data = self._auth.get(
            f"{self._backend_url}/v1/agents/{self._config.agent_id}/mcp/tools"
        )
        tools = data.get("tools", data.get("data", []))
        return tools if isinstance(tools, list) else []

    def close(self) -> None:
        self._auth.close()
        self._plain.close()

    def get_agent_config(self) -> dict[str, Any]:
        return self._auth.get(
            f"{self._runtime_url}/agent/config"
        )

    def promote_to_golden(self, trace_id: str) -> dict[str, Any]:
        """Promove um trace a golden (Fase E).

        Usa backend_url (porta 8002) — o endpoint de goldens está no backend
        TypeScript, não no runtime Python. Diferente de get_agent_config() que
        usa runtime_url (porta 8001).
        """
        return self._auth.post(
            f"{self._backend_url}/v1/evals/goldens/promote-from-trace/{trace_id}",
            {},
        )

    def promote_knowledge_unit(self, ku_id: str, confirmed_source_count: int = 1,
                                has_human_validation: bool = True) -> dict[str, Any]:
        """COUS v3.1 — Promove uma KnowledgeUnit após confirmação humana.

        Chamado quando o operador confirma um diagnóstico (/confirmar).
        Usa runtime_url (porta 8001) — o endpoint v3 está no runtime Python.
        """
        return self._auth.post(
            f"{self._runtime_url}/v3/knowledge-units/{ku_id}/promote",
            {
                "target_level": "confirmed",
                "confirmed_source_count": confirmed_source_count,
                "has_human_validation": has_human_validation,
                "has_open_contradictions": False,
            },
        )

    def create_knowledge_unit(self, domain_id: str, title: str, statement: str,
                               confidence: float = 0.8) -> dict[str, Any]:
        """COUS v3.1 — Cria uma nova KnowledgeUnit a partir de feedback confirmado.

        Usa runtime_url (porta 8001).
        """
        return self._auth.post(
            f"{self._runtime_url}/v3/knowledge-units",
            {
                "domain_id": domain_id,
                "title": title,
                "statement": statement,
                "knowledge_level": "experimental",
                "confidence": confidence,
            },
        )

    def _is_healthy(self, url: str) -> bool:
        try:
            return self._plain.get(url).is_success
        except httpx.RequestError:
            return False


__all__ = ["ClientError", "OpenTracyClient"]
