"""Token handling for OpenTracy authentication."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cous.config import AuthConfig, expand_path


class AuthError(Exception):
    """Authentication configuration error."""


class TokenProvider:
    def __init__(self, token_file: str, env_var: str) -> None:
        self._token_file = token_file
        self._env_var = env_var

    @classmethod
    def for_knowledge(cls, config: AuthConfig) -> TokenProvider:
        return cls(config.token_file, config.env_var)

    @classmethod
    def for_api(cls, config: AuthConfig) -> TokenProvider:
        return cls(config.api_token_file, config.api_env_var)

    def load(self) -> str:
        env_token = os.environ.get(self._env_var, "").strip()
        if env_token:
            return env_token
        return load_token_file(self._token_file)

    def status(self) -> dict[str, object]:
        env_present = bool(os.environ.get(self._env_var, "").strip())
        path = expand_path(self._token_file)
        if env_present:
            return {"source": "env", "env_var": self._env_var, "present": True}
        if not path.is_file():
            return {"source": "file", "path": str(path), "present": False}
        return {
            "source": "file",
            "path": str(path),
            "present": True,
            "secure": _is_permissions_600(path),
            "permissions": oct(path.stat().st_mode & 0o777),
        }


def load_token_file(token_file: str) -> str:
    path = expand_path(token_file)
    if not path.is_file():
        raise AuthError(f"Token nao encontrado em {path}")
    _check_permissions(path)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise AuthError(f"Arquivo de token vazio: {path}")
    return token


def save_token_file(token: str, token_file: str) -> Path:
    path = expand_path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip() + "\n", encoding="utf-8")
    _set_permissions_600(path)
    return path


def _check_permissions(path: Path) -> None:
    if os.name == "nt":
        return
    if not _is_permissions_600(path):
        raise AuthError(
            f"Arquivo de token {path} tem permissao {oct(path.stat().st_mode & 0o777)}. "
            f"Execute: chmod 0600 {path}"
        )


def _is_permissions_600(path: Path) -> bool:
    try:
        return path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR
    except OSError:
        return False


def _set_permissions_600(path: Path) -> None:
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
