"""Barra superior com dots de status e identificação do agente."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static


class TopBar(Static):
    """Barra superior fixa com dots de status dos servidores.

    Exibe: ● ● ●  cous — agente:<id>  backend● runtime● knowledge● measurements●
    Atualizada por StatusUpdated → on_status_updated().
    """

    DEFAULT_CSS = """
    TopBar {
        height: 1;
        background: #242528;
        border-bottom: solid #2E2F33;
        padding: 0 1;
        color: #C8C8C8;
    }
    """

    def __init__(self, agent_id: str = "cous") -> None:
        super().__init__()
        self.agent_id = agent_id
        self._backend_dot = "[#555]●[/]"
        self._runtime_dot = "[#555]●[/]"
        self._knowledge_dot = "[#555]●[/]"
        self._measurements_dot = "[#555]●[/]"

    def compose(self) -> ComposeResult:
        yield from ()  # Static não precisa de filhos

    def on_mount(self) -> None:
        self._refresh()

    def update_status(self, state: object) -> None:
        """Atualiza dots a partir de um AppState."""
        for comp in (state.backend, state.runtime, state.knowledge, state.measurements):
            dot = comp.dot
            if comp.name == "backend":
                self._backend_dot = dot
            elif comp.name == "runtime":
                self._runtime_dot = dot
            elif comp.name == "knowledge":
                self._knowledge_dot = dot
            elif comp.name == "measurements":
                self._measurements_dot = dot
        self._refresh()

    def _refresh(self) -> None:
        self.update(
            f" {self._backend_dot} {self._runtime_dot} {self._knowledge_dot} "
            f" {self._measurements_dot}  "
            f"cous — agente: {self.agent_id}"
        )
