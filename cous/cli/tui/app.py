"""Aplicação Textual principal do Cous TUI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static
from textual import on, work

from cous.cli.tui.events import ChatResponse, LogLineData, UserInput
from cous.cli.tui.state import AppState
from cous.cli.tui.widgets.bottombar import BottomBar
from cous.cli.tui.widgets.chat import ChatPanel
from cous.cli.tui.widgets.topbar import TopBar
from cous.clients.base import ClientError


class CousApp(App):
    """Aplicação Textual raiz do Cous.

    Layout fixo: TopBar + Horizontal(ChatPanel, Sidebar placeholder) + BottomBar.
    Workers assíncronos para chat e status.
    """

    CSS = """
    Screen {
        background: #1A1B1E;
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("escape", "focus_input", "Input", show=False),
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

        agent_id = getattr(getattr(config, "opentracy", None), "agent_id", "cous")
        self.state = AppState(agent_id=agent_id)

        # Populados em on_mount()
        self.ctx: object | None = None
        self.output_router: object | None = None

    def compose(self) -> ComposeResult:
        yield TopBar(agent_id=self.state.agent_id)
        with Horizontal():
            yield ChatPanel(id="chat-panel")
            yield Static("", id="sidebar")  # placeholder — Sprint 3
        yield BottomBar()

    def on_mount(self) -> None:
        """Inicializa componentes pós-compose."""
        from cous.application.session import ConversationStore
        from cous.cli.commands import build_router, CommandContext

        # Sessão
        session = (
            self._conversations.latest_session()
            if isinstance(self._conversations, ConversationStore)
            else None
        )
        if session is None and isinstance(self._conversations, ConversationStore):
            session = self._conversations.create_session()

        # CommandContext
        self.ctx = CommandContext(
            config=self._config,
            opentracy=self._opentracy,
            knowledge=self._knowledge,
            measurements=self._measurements,
            conversations=self._conversations,
            session=session,
            logger=self._logger,
            feedback_store=self._feedback_store,
            system_prompt_cache=self._system_prompt_cache,
            trace_emitter=self._trace_emitter,
            output_router=None,  # Sprint 4
        )

        self._command_router = build_router()

        # Boas-vindas
        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(
            f"Cous TUI — agente: {self.state.agent_id}\n"
            f"Sessão: {session.session_id if session else 'nova'}",
            role="system",
        )

        self.state.session_id = session.session_id if session else ""

    # ── Input handling ──────────────────────────────────────────────────

    @on(UserInput)
    def handle_user_input(self, event: UserInput) -> None:
        """Roteia input do operador: comandos → router, texto → chat worker."""
        text = event.text

        # Ecoar input do operador
        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(text, role="operator")

        # Comando?
        if text.startswith("/"):
            if self.ctx and hasattr(self, "_command_router"):
                result = self._command_router.dispatch(text, self.ctx)
                if result is False:
                    self.exit()
            return

        # Chat — worker assíncrono
        self._do_chat(text)

    # ── Chat worker ─────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _do_chat(self, text: str) -> None:
        """Worker de chat — executa _send_chat sem bloquear UI."""
        ctx = self.ctx
        if ctx is None:
            return

        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)

        # Indicador de pensando
        scroll.add_bubble("pensando...", role="system")

        # _send_chat
        ctx.session.add("user", text)
        if self._logger:
            self._logger.log("chat_user", session_id=ctx.session.session_id, text=text)

        history = ctx.session.history_for_model(ctx.config.memory.max_history)
        if ctx.system_prompt_cache is not None:
            system_prompt = ctx.system_prompt_cache.get()
            history.insert(0, {"role": "system", "content": system_prompt})

        try:
            result = ctx.opentracy.chat(
                text,
                history=history,
                session_id=ctx.session.session_id,
            )
        except ClientError as exc:
            self.post_message(LogLineData(level="error", text=str(exc)))
            return

        response = str(result.get("response") or "")
        ctx.session.add("assistant", response)
        trace_id = str(result.get("trace_id") or "")
        if trace_id:
            ctx.last_trace_id = trace_id

        # Trace
        if ctx.trace_emitter is not None:
            ctx.trace_emitter.emit_chat(
                trace_id=trace_id,
                session_id=ctx.session.session_id,
                channel="terminal",
                request=text,
                response=response,
                duration_ms=int(result.get("duration_ms") or 0),
                agent_version=str(result.get("agent_version") or ""),
                stages=result.get("stages"),
            )

        # Atualizar UI via mensagens (thread-safe)
        self.post_message(ChatResponse(
            text=response,
            trace_id=trace_id,
            stages=result.get("stages"),
        ))

        if self._logger:
            self._logger.log("chat_assistant", session_id=ctx.session.session_id,
                           trace_id=trace_id, text=response)

        # Resumo automático
        self._maybe_refresh_summary(ctx)

    # ── Handlers de mensagens ───────────────────────────────────────────

    @on(ChatResponse)
    def handle_chat_response(self, event: ChatResponse) -> None:
        """Exibe resposta do agente no ChatScroll (loop principal)."""
        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(event.text, role="agent", trace_id=event.trace_id)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _maybe_refresh_summary(self, ctx: object) -> None:
        """Resumo automático se acima do threshold."""
        limit = ctx.config.memory.max_chars_before_summary
        if ctx.session.pending_summary_chars() <= limit:
            return
        try:
            from cous.cli.commands import build_chat_summary
            summary = build_chat_summary(ctx)
            ctx.session.set_summary(summary)
            if self._logger:
                self._logger.log("summary_updated", session_id=ctx.session.session_id, automatic=True)
        except Exception:
            pass  # fallback local silencioso no TUI

    def action_focus_input(self) -> None:
        """Binding: foca no InputBar."""
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass
