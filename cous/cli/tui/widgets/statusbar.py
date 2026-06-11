"""Barra de status horizontal — 4 componentes em linha."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container

from cous.cli.tui.widgets.status import StatusRow


class StatusBar(Container):
    """Linha de status horizontal abaixo da TopBar."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        layout: horizontal;
        background: #1E1F22;
        padding: 0 2;
    }
    StatusRow {
        width: 1fr;
        height: 1;
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
        for comp in (state.backend, state.runtime, state.knowledge, state.measurements):
            row = self._rows.get(comp.name)
            if row:
                row.update_status(comp.state, comp.detail)
