"""HTTP callback server for OpenTracy diagnosis results."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from cous.clients.diagnosis import DiagnosisCallbackHandler
from cous.config import Config, expand_path
from cous.contracts.callback_handler import create_callback_router
from cous.measurements.store import MeasurementLocalStore


def create_callback_app(config: Config) -> FastAPI:
    storage_path = expand_path(config.measurements.storage_file)
    store = MeasurementLocalStore(storage_path)
    handler = DiagnosisCallbackHandler(store)
    app = FastAPI(title="Cous Diagnosis Callback", version="0.1.0")
    app.include_router(create_callback_router(handler))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "storage_file": str(storage_path)}

    return app


def run_callback_server(config: Config, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(create_callback_app(config), host=host, port=port)


@dataclass
class BackgroundCallbackServer:
    server: Any
    thread: threading.Thread
    url: str
    endpoint: str

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def start_background_callback_server(
    config: Config,
) -> BackgroundCallbackServer | None:
    """Starts the callback server used by diagnosis v3 while the TUI is running.

    If the configured port is already in use, use a nearby free port and update
    the callback endpoint that will be sent to OpenTracy.
    """
    import uvicorn

    parts = urlsplit(config.opentracy.diagnosis_callback_endpoint)
    host = parts.hostname or "127.0.0.1"
    if host == "localhost":
        host = "127.0.0.1"
    port = _resolve_callback_port(
        host,
        parts.port or (443 if parts.scheme == "https" else 80),
    )
    if port is None:
        return None
    endpoint = urlunsplit((
        parts.scheme or "http",
        f"{host}:{port}",
        parts.path or "/cous/diagnosis/callback",
        parts.query,
        parts.fragment,
    ))
    config.opentracy.diagnosis_callback_endpoint = endpoint

    server = uvicorn.Server(
        uvicorn.Config(
            create_callback_app(config),
            host=host,
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(
        target=server.run,
        name="cous-diagnosis-callback",
        daemon=True,
    )
    thread.start()
    return BackgroundCallbackServer(
        server=server,
        thread=thread,
        url=f"http://{host}:{port}",
        endpoint=endpoint,
    )


def _resolve_callback_port(host: str, preferred_port: int) -> int | None:
    if _can_bind(host, preferred_port):
        return preferred_port
    for port in range(8010, 8030):
        if _can_bind(host, port):
            return port
    return None


def _can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError:
        return False
    return True
