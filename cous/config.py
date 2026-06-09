"""Typed configuration for the Cous thin client."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OpenTracyConfig(BaseModel):
    backend_url: str = "http://localhost:8002"
    runtime_url: str = "http://localhost:8001"
    agent_id: str = "cous"
    timeout: int = 30

    @field_validator("timeout")
    @classmethod
    def positive_timeout(cls, value: int) -> int:
        return value if value > 0 else 30


class AuthConfig(BaseModel):
    token_file: str = "~/.cous/opentracy_token"
    env_var: str = "COUS_OPENTRACY_TOKEN"
    api_token_file: str = "~/.ligadoai/api_token"
    api_env_var: str = "COUS_OPENTRACY_API_TOKEN"
    opentracy_env_file: str = "../OpenTracy/.env"
    opentracy_env_key: str = "OPENTRACY_KNOWLEDGE_AUTH_TOKEN"
    opentracy_measurements_env_key: str = "OPENTRACY_MEASUREMENTS_AUTH_TOKEN"


class MemoryConfig(BaseModel):
    max_history: int = 10
    max_chars_before_summary: int = 16000

    @field_validator("max_history")
    @classmethod
    def positive_history(cls, value: int) -> int:
        return max(1, value)


class MeasurementsConfig(BaseModel):
    storage_file: str = ".cous-data/measurements.json"


class ChatConfig(BaseModel):
    conversations_dir: str = ".cous-data/conversations"


class MpcConfig(BaseModel):
    timeout_seconds: int = 30
    max_restarts: int = 3
    restart_backoff_seconds: int = 5


class KnowledgeConfig(BaseModel):
    poll_timeout_seconds: int = 120


class LogsConfig(BaseModel):
    events_file: str = ".cous-data/logs/events.jsonl"


class Config(BaseModel):
    opentracy: OpenTracyConfig = OpenTracyConfig()
    auth: AuthConfig = AuthConfig()
    memory: MemoryConfig = MemoryConfig()
    measurements: MeasurementsConfig = MeasurementsConfig()
    chat: ChatConfig = ChatConfig()
    mcp: MpcConfig = MpcConfig()
    logs: LogsConfig = LogsConfig()
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)


def load_config(path: Path | None = None) -> Config:
    config_path = path or _find_config()
    if config_path is None or not config_path.is_file():
        return Config()
    raw = _read_toml(config_path)
    return Config(**raw)


def expand_path(value: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(value))).resolve()


def _find_config() -> Path | None:
    candidates = [
        Path.cwd() / "config.toml",
        Path(__file__).resolve().parent.parent / "config.toml",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _read_toml(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)
