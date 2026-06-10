"""Worker de polling de status dos servidores OpenTracy."""

from __future__ import annotations

import asyncio

from cous.cli.tui.events import StatusUpdated
from cous.cli.tui.state import ComponentStatus


class StatusPoller:
    """Worker que faz polling de health() a cada N segundos.

    Atualiza AppState e posta StatusUpdated para TopBar + StatusPanel.
    """

    def __init__(
        self,
        opentracy: object,
        knowledge: object,
        measurements: object,
        state: object,
        app: object,
        interval: int = 15,
    ) -> None:
        self._opentracy = opentracy
        self._knowledge = knowledge
        self._measurements = measurements
        self._state = state
        self._app = app
        self._interval = interval
        self._failures = 0

    async def run(self) -> None:
        """Loop de polling — chamado como worker Textual."""
        while True:
            try:
                await self._poll()
            except Exception:
                pass
            await asyncio.sleep(self._interval)

    async def _poll(self) -> None:
        """Executa uma rodada de health checks."""
        # Backend + Runtime
        try:
            health = self._opentracy.health()
            self._state.backend = ComponentStatus(
                "backend",
                "ok" if health.get("backend") else "down",
            )
            self._state.runtime = ComponentStatus(
                "runtime",
                "ok" if health.get("runtime") else "down",
            )
        except Exception:
            self._state.backend = ComponentStatus("backend", "down")
            self._state.runtime = ComponentStatus("runtime", "down")

        # Knowledge
        try:
            ks = self._knowledge.status()
            self._state.knowledge = ComponentStatus(
                "knowledge",
                "ok" if ks.get("status") == "ready" else "warn",
                f"docs={ks.get('document_count', 0)}",
            )
        except Exception:
            self._state.knowledge = ComponentStatus("knowledge", "down")

        # Measurements
        try:
            ms = self._measurements.status()
            self._state.measurements = ComponentStatus(
                "measurements",
                "ok" if ms.get("enabled") else "warn",
                f"backend={ms.get('backend', '?')}",
            )
        except Exception:
            self._state.measurements = ComponentStatus("measurements", "down")

        # Postar atualização
        self._app.post_message(StatusUpdated(self._state))

        # Backoff em falha
        if all(c.state == "down" for c in (
            self._state.backend, self._state.runtime,
            self._state.knowledge, self._state.measurements
        )):
            self._failures += 1
        else:
            self._failures = 0

        if self._failures >= 3:
            self._interval = min(self._interval * 2, 120)
        elif self._failures == 0:
            self._interval = 15
