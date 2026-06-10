"""Painel de stages do pipeline (pós-chat)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class StagesPanel(Container):
    """Painel de stages do pipeline retrieve→rerank→route→generate.

    Aparece após cada resposta do agente com os tempos de cada etapa.
    Colapsável — implementado no Sidebar.
    """

    DEFAULT_CSS = """
    StagesPanel {
        padding: 0;
        border-bottom: solid #2E2F33;
    }
    StagesPanel Static {
        height: 1;
        padding: 0 1;
        color: #888888;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._content = Static("")

    def compose(self) -> ComposeResult:
        yield self._content

    def update(self, stages: list[dict]) -> None:
        """Atualiza com os stages do trace."""
        if not stages:
            self._content.update("[dim](sem stages)[/]")
            return

        lines = []
        for s in stages:
            stage_name = s.get("stage", "?")
            duration = s.get("duration_ms", 0)
            technique = s.get("technique", "")
            error = s.get("error")

            if error:
                lines.append(f" [red]✗[/] {stage_name:<10} [red]{error}[/]")
            else:
                lines.append(f" [green]✓[/] {stage_name:<10} {duration}ms {technique}")

        self._content.update("\n".join(lines))
