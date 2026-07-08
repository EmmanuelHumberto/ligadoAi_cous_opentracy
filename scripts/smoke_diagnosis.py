"""Smoke test for the COUS/OpenTracy diagnosis path.

This script does not enqueue a diagnosis. It checks whether the services needed
for `/diagnostico <id>` are reachable and consistently configured.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from cous.auth import TokenProvider
from cous.config import Config, expand_path, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test COUS diagnosis setup")
    parser.add_argument("--config", type=str, default=None, help="Path to config.toml")
    parser.add_argument(
        "--callback-url",
        type=str,
        default=None,
        help="Override callback URL to test",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)
    callback_url = args.callback_url or config.opentracy.diagnosis_callback_endpoint
    token = _load_token(config)

    checks = [
        _check_runtime_health(config),
        _check_diagnosis_status(config, token),
        _check_callback_server(callback_url),
        _check_local_identity_config(config),
    ]

    ok = True
    for name, passed, detail in checks:
        marker = "ok" if passed else "fail"
        print(f"[{marker}] {name}: {detail}")
        ok = ok and passed

    return 0 if ok else 1


def _load_token(config: Config) -> str:
    try:
        provider = TokenProvider.for_knowledge(config.auth)
        return provider.load()
    except Exception:
        return ""


def _check_runtime_health(config: Config) -> tuple[str, bool, str]:
    url = f"{config.opentracy.runtime_url.rstrip('/')}/health"
    try:
        response = httpx.get(url, timeout=config.opentracy.timeout)
        return "runtime health", response.is_success, f"{response.status_code} {url}"
    except httpx.RequestError as exc:
        return "runtime health", False, str(exc)


def _check_diagnosis_status(config: Config, token: str) -> tuple[str, bool, str]:
    url = f"{config.opentracy.runtime_url.rstrip('/')}/v3/diagnosis/status"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(url, headers=headers, timeout=config.opentracy.timeout)
    except httpx.RequestError as exc:
        return "diagnosis runtime", False, str(exc)

    if not response.is_success:
        return "diagnosis runtime", False, f"{response.status_code} {response.text[:160]}"

    try:
        payload = response.json()
    except ValueError:
        return "diagnosis runtime", False, "response is not JSON"

    status = str(payload.get("status") or "unknown")
    db = bool(payload.get("database_configured"))
    worker = bool(payload.get("worker_enabled"))
    running = bool(payload.get("worker_running"))
    ok = status == "available" and db and worker and running
    return (
        "diagnosis runtime",
        ok,
        f"status={status} db={db} worker={worker} running={running}",
    )


def _check_callback_server(callback_url: str) -> tuple[str, bool, str]:
    status_url = _callback_status_url(callback_url)
    try:
        response = httpx.get(status_url, timeout=5)
        return "callback server", response.is_success, f"{response.status_code} {status_url}"
    except httpx.RequestError as exc:
        return "callback server", False, str(exc)


def _callback_status_url(callback_url: str) -> str:
    parts = urlsplit(callback_url)
    path = parts.path.rstrip("/")
    if path.endswith("/callback"):
        path = path.removesuffix("/callback") + "/callback/status"
    elif not path.endswith("/callback/status"):
        path = path + "/callback/status"
    return parts._replace(path=path, query="", fragment="").geturl()


def _check_local_identity_config(config: Config) -> tuple[str, bool, str]:
    auto = config.opentracy.diagnosis_auto_resolve_identity
    domain_id = bool(config.opentracy.diagnosis_domain_id.strip())
    instance_id = bool(config.opentracy.diagnosis_instance_id.strip())
    storage = expand_path(config.measurements.storage_file)
    ok = auto or (domain_id and instance_id)
    detail = (
        f"auto_resolve={auto} domain_id={domain_id} "
        f"instance_id={instance_id} store={storage}"
    )
    return "local diagnosis config", ok, detail


if __name__ == "__main__":
    raise SystemExit(main())
