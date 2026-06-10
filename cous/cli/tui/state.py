"""Estado compartilhado da aplicação TUI.

AppState é uma dataclass reativa que centraliza todos os dados que os widgets
precisam exibir. Nenhum widget acessa diretamente OpenTracyClient ou
MeasurementsClient — toda comunicação passa por este estado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ServerStatus = Literal["ok", "warn", "down", "unknown"]


@dataclass
class ComponentStatus:
    """Status de um componente do ecossistema OpenTracy."""

    name: str  # "backend", "runtime", "knowledge", "measurements"
    state: ServerStatus = "unknown"
    detail: str = "-"

    @property
    def dot(self) -> str:
        """Retorna o símbolo de dot colorido para Textual."""
        dots = {"ok": "[#639922]●[/]", "warn": "[#EF9F27]●[/]",
                "down": "[#E24B4A]●[/]", "unknown": "[#555]●[/]"}
        return dots.get(self.state, dots["unknown"])


@dataclass
class AppState:
    """Estado global da aplicação Cous TUI.

    Atualizado pelo StatusPoller e pelo ChatWorker. Lido por TopBar,
    StatusPanel, StagesPanel e BottomBar via reactive properties.
    """

    agent_id: str = ""
    session_id: str = ""

    # Componentes do ecossistema
    backend: ComponentStatus = field(default_factory=lambda: ComponentStatus("backend"))
    runtime: ComponentStatus = field(default_factory=lambda: ComponentStatus("runtime"))
    knowledge: ComponentStatus = field(default_factory=lambda: ComponentStatus("knowledge"))
    measurements: ComponentStatus = field(default_factory=lambda: ComponentStatus("measurements"))

    # Último trace
    last_trace_id: str = ""
    last_stages: list[dict] = field(default_factory=list)

    # Modelo e tokens
    model_name: str = ""
    token_count: int = 0
    is_thinking: bool = False

    # Conexão
    tui_mode: bool = True
