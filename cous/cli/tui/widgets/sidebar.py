"""Sidebar — orquestrador dos painéis laterais."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Collapsible, Static

from cous.cli.tui.widgets.log_panel import LogPanel
from cous.cli.tui.widgets.stages import StagesPanel
from cous.cli.tui.widgets.status import StatusPanel


class SidePanel(Container):
    """Painel de dados expansível para tabelas de /buscar, /indexados, etc."""

    DEFAULT_CSS = """
    SidePanel {
        padding: 0;
        border-bottom: solid #2E2F33;
        max-height: 20;
    }
    SidePanel Static {
        padding: 0 1;
        color: #C8C8C8;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._title = "Dados"
        self._content = Static("")

    def compose(self) -> ComposeResult:
        yield self._content

    def show_data(self, title: str, rows: list[str]) -> None:
        """Exibe dados tabulares no painel."""
        self._title = title
        self._content.update("\n".join(rows[:30]))  # limita 30 linhas


class Sidebar(Container):
    """Barra lateral com painéis colapsáveis.

    Layout:
      StatusPanel (sempre visível)
      StagesPanel (após chat)
      SidePanel (tabelas de dados)
      LogPanel (stream de eventos)
    """

    DEFAULT_CSS = """
    Sidebar {
        width: 28;
        min-width: 24;
        max-width: 36;
        background: #1E1F22;
        border-left: solid #2E2F33;
    }
    Sidebar Collapsible {
        border-bottom: solid #2E2F33;
    }
    """

    def compose(self) -> ComposeResult:
        with Collapsible(title="STATUS"):
            yield StatusPanel(id="status-panel")

        with Collapsible(title="PIPELINE", collapsed=True):
            yield StagesPanel(id="stages-panel")

        with Collapsible(title="DADOS", collapsed=True):
            yield SidePanel(id="side-panel")

        with Collapsible(title="LOGS"):
            yield LogPanel(id="log-panel")
