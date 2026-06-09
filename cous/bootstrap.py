"""Local bootstrap for Cous/OpenTracy authentication."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx

from cous.auth import load_token_file, save_token_file
from cous.config import AuthConfig, Config, expand_path


@dataclass(frozen=True)
class BootstrapResult:
    token_file: Path
    api_token_file: Path
    opentracy_env_file: Path
    token_created: bool
    api_token_created: bool
    env_updated: bool
    agent_created: bool
    api_connected: bool
    public_url: str


def bootstrap_auth(config: Config) -> BootstrapResult:
    auth = config.auth
    token_created = False
    try:
        token = load_token_file(auth.token_file)
    except Exception:
        token = secrets.token_urlsafe(32)
        save_token_file(token, auth.token_file)
        token_created = True

    env_file = expand_path(auth.opentracy_env_file)
    env_updated = upsert_env_value(env_file, auth.opentracy_env_key, token)
    env_updated = (
        upsert_env_value(env_file, auth.opentracy_measurements_env_key, token) or env_updated
    )

    api_result = _ensure_api_channel(config)
    api_token_created = False
    if api_result.token:
        save_token_file(api_result.token, auth.api_token_file)
        api_token_created = True

    return BootstrapResult(
        token_file=expand_path(auth.token_file),
        api_token_file=expand_path(auth.api_token_file),
        opentracy_env_file=env_file,
        token_created=token_created,
        api_token_created=api_token_created,
        env_updated=env_updated,
        agent_created=api_result.agent_created,
        api_connected=api_result.api_connected,
        public_url=api_result.public_url,
    )


@dataclass(frozen=True)
class ApiBootstrapResult:
    token: str
    agent_created: bool
    api_connected: bool
    public_url: str


def _ensure_api_channel(config: Config) -> ApiBootstrapResult:
    runtime_url = config.opentracy.runtime_url.rstrip("/")
    agent_id = config.opentracy.agent_id
    api_token_file = expand_path(config.auth.api_token_file)
    public_url = f"{runtime_url}/api/{agent_id}/chat"
    timeout = httpx.Timeout(config.opentracy.timeout)
    agent_created = False
    api_connected = False

    try:
        with httpx.Client(timeout=timeout) as client:
            agent_response = client.get(f"{runtime_url}/agents/{agent_id}")
            if agent_response.status_code == 404:
                create_response = client.post(
                    f"{runtime_url}/agents",
                    json={
                        "name": agent_id,
                        "prompt": "Cous terminal agent",
                        "channels": ["api"],
                        "activate": False,
                    },
                )
                create_response.raise_for_status()
                agent_created = True
            elif agent_response.is_error:
                agent_response.raise_for_status()

            connect_response = client.post(f"{runtime_url}/agents/{agent_id}/channels/api/connect")
            if connect_response.status_code == 409:
                if api_token_file.is_file():
                    token = ""
                    api_connected = True
                else:
                    rotate_response = client.post(
                        f"{runtime_url}/agents/{agent_id}/channels/api/rotate"
                    )
                    rotate_response.raise_for_status()
                    payload = rotate_response.json()
                    token = str(payload.get("token") or "")
                    api_connected = True
                    public_url = str(payload.get("public_url") or public_url)
            else:
                connect_response.raise_for_status()
                payload = connect_response.json()
                token = str(payload.get("token") or "")
                api_connected = True
                public_url = str(payload.get("public_url") or public_url)
            return ApiBootstrapResult(
                token=token,
                agent_created=agent_created,
                api_connected=api_connected,
                public_url=public_url,
            )
    except Exception:
        return ApiBootstrapResult(
            token="",
            agent_created=agent_created,
            api_connected=False,
            public_url=public_url,
        )


def upsert_env_value(path: Path, key: str, value: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    next_line = f'{key}="{value}"'
    changed = False
    found = False
    updated_lines: list[str] = []

    for line in lines:
        if line.strip().startswith(f"{key}="):
            found = True
            if line != next_line:
                changed = True
            updated_lines.append(next_line)
            continue
        updated_lines.append(line)

    if not found:
        if updated_lines and updated_lines[-1] != "":
            updated_lines.append("")
        updated_lines.append(next_line)
        changed = True

    if changed:
        path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return changed
