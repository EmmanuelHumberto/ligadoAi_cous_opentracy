"""Shared HTTP helpers."""

from __future__ import annotations

import time as _time
from typing import Any

import httpx

from cous.auth import TokenProvider

_RETRYABLE_STATUS = {429, 502, 503, 504}
_DEFAULT_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0


class ClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticatedHttpClient:
    def __init__(self, *, token_provider: TokenProvider, timeout: int, retries: int = _DEFAULT_RETRIES) -> None:
        self._token_provider = token_provider
        self._http = httpx.Client(timeout=httpx.Timeout(timeout))
        self._retries = retries

    def get(self, url: str) -> dict[str, Any]:
        response = self._request("GET", url)
        return _json_object(response)

    def post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", url, json=payload)
        return _json_object(response)

    def delete(self, url: str) -> None:
        self._request("DELETE", url)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token_provider.load()}"

        # Retry automático apenas para GET (idempotente).
        # POST/DELETE podem duplicar recursos — o chamador decide.
        max_attempts = self._retries + 1 if method == "GET" else 1

        for attempt in range(max_attempts):
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < max_attempts - 1:
                    _time.sleep(_RETRY_BASE_SECONDS * (2 ** attempt))
                    continue
                raise ClientError(
                    "Timeout ao comunicar com OpenTracy"
                    if isinstance(exc, httpx.TimeoutException)
                    else f"Falha de conexao com OpenTracy: {exc}"
                ) from exc

            # Sem retry para erros de autenticação — não são transitórios
            if response.status_code == 401:
                raise ClientError("Token ausente, invalido ou expirado", status_code=401)
            if response.status_code == 403:
                raise ClientError("Token valido, mas sem permissao para esta acao", status_code=403)

            # Retry apenas para GET com 5xx transitórios
            if method == "GET" and response.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                _time.sleep(_RETRY_BASE_SECONDS * (2 ** attempt))
                continue

            if not response.is_success:
                raise ClientError(
                    f"HTTP {response.status_code}: {_response_detail(response)}",
                    status_code=response.status_code,
                )
            return response

        raise ClientError("Falha após todas as tentativas")


def _json_object(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def _response_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict):
        return str(data.get("detail") or data.get("error") or data)[:300]
    return str(data)[:300]
