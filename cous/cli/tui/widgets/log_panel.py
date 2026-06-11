"""Painel de log com stream de eventos em tempo real."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog


class LogPanel(Container):
    """Painel de log com RichLog para stream de eventos.

    Exibe linhas de log com ícones por nível:
      [red]▸[/] error   [dim]▸[/] info   [green]▸[/] success   [yellow]▸[/] warning
    """

    DEFAULT_CSS = """
    LogPanel {
        height: 1fr;
        padding: 0;
    }
    LogPanel RichLog {
        padding: 0 1;
        color: #888888;
        background: #1E1F22;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, max_lines=200)

    def add_line(self, level: str, text: str) -> None:
        """Adiciona uma linha de log com ícone."""
        icons = {"error": "[red]▸[/]", "info": "[dim]▸[/]", "success": "[green]▸[/]", "warning": "[yellow]▸[/]"}
        icon = icons.get(level, "•")
        log = self.query_one(RichLog)
        log.write(f"{icon} {text}")
