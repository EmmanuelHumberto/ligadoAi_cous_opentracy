"""Client for the OpenTracy knowledge vertical."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cous.auth import TokenProvider
from cous.clients.base import AuthenticatedHttpClient
from cous.config import OpenTracyConfig


class KnowledgeClient:
    def __init__(self, config: OpenTracyConfig, token_provider: TokenProvider) -> None:
        self._http = AuthenticatedHttpClient(
            token_provider=token_provider,
            timeout=config.timeout,
        )
        self._runtime_url = config.runtime_url.rstrip("/")

    def index(
        self,
        path: Path,
        *,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "source_uri": str(path),
            "metadata": metadata or {},
            "options": {"force": force, "dry_run": dry_run},
        }
        return self._http.post(f"{self._runtime_url}/knowledge/index", payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._http.get(f"{self._runtime_url}/knowledge/jobs/{job_id}")

    def validate(self, path: Path) -> dict[str, Any]:
        return self._http.post(
            f"{self._runtime_url}/knowledge/validate",
            {"source_uri": str(path)},
        )

    def status(self) -> dict[str, Any]:
        return self._http.get(f"{self._runtime_url}/knowledge/status")

    def list_documents(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        suffix = "?include_deleted=true" if include_deleted else ""
        data = self._http.get(f"{self._runtime_url}/knowledge/documents{suffix}")
        documents = data.get("documents", [])
        return documents if isinstance(documents, list) else []

    def search(self, query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
        data = self._http.post(
            f"{self._runtime_url}/knowledge/search",
            {"query": query, "top_k": top_k},
        )
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    def delete_document(self, document_id: str) -> None:
        self._http.delete(f"{self._runtime_url}/knowledge/documents/{document_id}")

    def close(self) -> None:
        self._http.close()
