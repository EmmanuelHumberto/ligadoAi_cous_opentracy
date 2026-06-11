"""Painel de status dos componentes OpenTracy."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class StatusRow(Static):
    """Uma linha de status: nome + dot + estado."""

    DEFAULT_CSS = """
    StatusRow {
        height: 1;
        padding: 0 1;
        color: #C8C8C8;
    }
    """

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._name = name
        self._state = "unknown"
        self._detail = "-"

    def on_mount(self) -> None:
        self._refresh_display()

    def update_status(self, state: str, detail: str = "-") -> None:
        self._state = state
        self._detail = detail
        self._refresh_display()

    def _refresh_display(self) -> None:
        colors = {"ok": "#639922", "warn": "#EF9F27",
                  "down": "#E24B4A", "unknown": "#555"}
        color = colors.get(self._state, colors["unknown"])
        self.update(f" [{color}]{self._name}[/]")


class StatusPanel(Container):
    """Painel de status com uma linha por componente.

    Colapsável — implementado no Sidebar como Collapsible.
    """

    DEFAULT_CSS = """
    StatusPanel {
        height: 4;
        padding: 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows: dict[str, StatusRow] = {}

    def compose(self) -> ComposeResult:
        for name in ("backend", "runtime", "knowledge", "measurements"):
            row = StatusRow(name)
            self._rows[name] = row
            yield row

    def update_from_state(self, state: object) -> None:
        """Atualiza todas as rows a partir de um AppState."""
        for comp in (state.backend, state.runtime, state.knowledge, state.measurements):
            row = self._rows.get(comp.name)
            if row:
                row.update_status(comp.state, comp.detail)
