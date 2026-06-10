"""Aplicação Textual principal do Cous TUI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from cous.cli.tui.state import AppState


class CousApp(App):
    """Aplicação Textual raiz do Cous.

    Layout fixo com TopBar, ChatPanel, Sidebar e BottomBar.
    Workers assíncronos para chat, comandos e polling de status.
    """

    CSS = """
    Screen {
        background: #1A1B1E;
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
    ]

    def __init__(
        self,
        config: object,
        opentracy: object,
        knowledge: object,
        measurements: object,
        conversations: object,
        logger: object,
        *,
        feedback_store: object = None,
        system_prompt_cache: object = None,
        trace_emitter: object = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._opentracy = opentracy
        self._knowledge = knowledge
        self._measurements = measurements
        self._conversations = conversations
        self._logger = logger
        self._feedback_store = feedback_store
        self._system_prompt_cache = system_prompt_cache
        self._trace_emitter = trace_emitter

        # Estado compartilhado
        agent_id = getattr(getattr(config, "opentracy", None), "agent_id", "cous")
        self.state = AppState(agent_id=agent_id)

        # Estes serão populados em on_mount() quando o loop de eventos iniciar
        self.ctx: object | None = None
        self.output_router: object | None = None

    def compose(self) -> ComposeResult:
        """Monta o layout base — widgets placeholder do Sprint 1."""
        yield Static(
            f"Cous TUI — agente: {self.state.agent_id}  (Sprint 1: layout vazio)",
            id="topbar",
        )
        yield Static("ChatPanel placeholder", id="chat")
        yield Static("Sidebar placeholder", id="sidebar")
        yield Static("BottomBar placeholder", id="bottombar")

    def on_mount(self) -> None:
        """Inicializa componentes que dependem do loop de eventos ativo."""
        # Placeholder — Sprint 2+ implementará OutputRouter, workers, etc.
        pass
