"""Local bootstrap for Cous/OpenTracy authentication."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from cous.auth import load_token_file, save_token_file
from cous.config import AuthConfig, expand_path


@dataclass(frozen=True)
class BootstrapResult:
    token_file: Path
    opentracy_env_file: Path
    token_created: bool
    env_updated: bool


def bootstrap_auth(config: AuthConfig) -> BootstrapResult:
    token_created = False
    try:
        token = load_token_file(config.token_file)
    except Exception:
        token = secrets.token_urlsafe(32)
        save_token_file(token, config.token_file)
        token_created = True

    env_file = expand_path(config.opentracy_env_file)
    env_updated = upsert_env_value(env_file, config.opentracy_env_key, token)
    return BootstrapResult(
        token_file=expand_path(config.token_file),
        opentracy_env_file=env_file,
        token_created=token_created,
        env_updated=env_updated,
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
