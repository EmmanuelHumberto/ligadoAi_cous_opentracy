"""Shared HTTP helpers."""

from __future__ import annotations

from typing import Any

import httpx

from cous.auth import TokenProvider


class ClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticatedHttpClient:
    def __init__(self, *, token_provider: TokenProvider, timeout: int) -> None:
        self._token_provider = token_provider
        self._http = httpx.Client(timeout=httpx.Timeout(timeout))

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
        try:
            response = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise ClientError("Timeout ao comunicar com OpenTracy") from exc
        except httpx.RequestError as exc:
            raise ClientError(f"Falha de conexao com OpenTracy: {exc}") from exc

        if response.status_code == 401:
            raise ClientError("Token ausente, invalido ou expirado", status_code=401)
        if response.status_code == 403:
            raise ClientError("Token valido, mas sem permissao para esta acao", status_code=403)
        if not response.is_success:
            raise ClientError(
                f"HTTP {response.status_code}: {_response_detail(response)}",
                status_code=response.status_code,
            )
        return response


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
