"""Painel de log com stream de eventos em tempo real."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog


class LogPanel(Container):
    """Painel de log com RichLog para stream de eventos.

    Exibe linhas de log com ícones por nível:
      ❌ error   ℹ️ info   ✅ success   ⚠️ warning
    """

    DEFAULT_CSS = """
    LogPanel {
        padding: 0;
        border-bottom: solid #2E2F33;
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
        icons = {"error": "❌", "info": "ℹ️", "success": "✅", "warning": "⚠️"}
        icon = icons.get(level, "•")
        log = self.query_one(RichLog)
        log.write(f"{icon} {text}")
