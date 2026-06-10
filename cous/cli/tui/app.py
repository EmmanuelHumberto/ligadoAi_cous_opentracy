"""Aplicação Textual principal do Cous TUI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual import on, work

from cous.cli.tui.events import (
    ChatResponse, ChatSessionsData, DocumentsData,
    JobProgressData, LogLineData, MeasurementDetailData,
    MeasurementsData, PromptRequest, PromptResponse,
    SearchResultsData, StatusUpdated, UserInput,
)
from cous.cli.tui.output_router import OutputRouter
from cous.cli.tui.poller import StatusPoller
from cous.cli.tui.state import AppState
from cous.cli.tui.widgets.bottombar import BottomBar
from cous.cli.tui.widgets.chat import ChatPanel
from cous.cli.tui.widgets.sidebar import Sidebar
from cous.cli.tui.widgets.topbar import TopBar
from cous.clients.base import ClientError


class CousApp(App):
    """Aplicação Textual raiz do Cous.

    Layout fixo: TopBar + Horizontal(ChatPanel, Sidebar) + BottomBar.
    Workers: ChatWorker, StatusPoller.
    """

    CSS = """
    Screen {
        background: #1A1B1E;
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("ctrl+s", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+r", "clear_chat", "Limpar", show=False),
        Binding("f1", "show_help", "Ajuda", show=True),
        Binding("escape", "focus_input", "Input", show=False),
    ]

    def __init__(
        self,
        config: object,
        opentracy: object,
        knowledge: object,
        measurements: object,
        conversations: object,
        event_logger: object,
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
        self._event_log = event_logger  # renomeado para evitar conflito textual
        self._feedback_store = feedback_store
        self._system_prompt_cache = system_prompt_cache
        self._trace_emitter = trace_emitter

        agent_id = getattr(getattr(config, "opentracy", None), "agent_id", "cous")
        self.state = AppState(agent_id=agent_id)

        self.ctx: object | None = None
        self.output_router: object | None = None
        self._command_router: object | None = None
        self._active_prompt: object | None = None  # PromptRequest ativo

    def compose(self) -> ComposeResult:
        yield TopBar(agent_id=self.state.agent_id)
        with Horizontal():
            yield ChatPanel(id="chat-panel")
            yield Sidebar(id="sidebar")
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

        self.ctx = CommandContext(
            config=self._config,
            opentracy=self._opentracy,
            knowledge=self._knowledge,
            measurements=self._measurements,
            conversations=self._conversations,
            session=session,
            logger=self._event_log,
            feedback_store=self._feedback_store,
            system_prompt_cache=self._system_prompt_cache,
            trace_emitter=self._trace_emitter,
            output_router=None,  # populado abaixo
        )
        self._command_router = build_router()

        # OutputRouter — thread-safe após on_mount
        self.output_router = OutputRouter(self)
        self.ctx.output_router = self.output_router
        self.output_router.flush_pending()

        # Boas-vindas
        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(
            f"Cous TUI — agente: {self.state.agent_id}\n"
            f"Sessão: {session.session_id if session else 'nova'}",
            role="system",
        )
        self.state.session_id = session.session_id if session else ""

        # StatusPoller
        tui_cfg = getattr(self._config, "tui", None)
        interval = getattr(tui_cfg, "status_poll_interval", 15) if tui_cfg else 15
        self._poller = StatusPoller(
            opentracy=self._opentracy,
            knowledge=self._knowledge,
            measurements=self._measurements,
            state=self.state,
            app=self,
            interval=interval,
        )
        self.run_worker(self._poller.run(), exclusive=False)

    # ── Input handling ──────────────────────────────────────────────────

    @on(UserInput)
    def handle_user_input(self, event: UserInput) -> None:
        text = event.text

        # Se há um prompt ativo, responde a ele
        if self._active_prompt:
            req = self._active_prompt
            self._active_prompt = None
            if req.result is not None:
                req.result[0] = text
            if req.event is not None:
                req.event.set()
            return

        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(text, role="operator")

        if text.startswith("/"):
            if self.ctx and self._command_router:
                self._do_command(text)
            return

        self._do_chat(text)

    # ── Chat worker ─────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _do_chat(self, text: str) -> None:
        ctx = self.ctx
        if ctx is None:
            return

        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble("pensando...", role="system")

        ctx.session.add("user", text)
        if self._event_log:
            self._event_log.log("chat_user", session_id=ctx.session.session_id, text=text)

        history = ctx.session.history_for_model(ctx.config.memory.max_history)
        if ctx.system_prompt_cache is not None:
            system_prompt = ctx.system_prompt_cache.get()
            history.insert(0, {"role": "system", "content": system_prompt})

        try:
            result = ctx.opentracy.chat(
                text, history=history, session_id=ctx.session.session_id,
            )
        except ClientError as exc:
            self.post_message(LogLineData(level="error", text=str(exc)))
            return

        response = str(result.get("response") or "")
        ctx.session.add("assistant", response)
        trace_id = str(result.get("trace_id") or "")
        if trace_id:
            ctx.last_trace_id = trace_id

        if ctx.trace_emitter is not None:
            ctx.trace_emitter.emit_chat(
                trace_id=trace_id, session_id=ctx.session.session_id,
                channel="terminal", request=text, response=response,
                duration_ms=int(result.get("duration_ms") or 0),
                agent_version=str(result.get("agent_version") or ""),
                stages=result.get("stages"),
            )

        self.post_message(ChatResponse(
            text=response, trace_id=trace_id,
            stages=result.get("stages"),
        ))

        if self._event_log:
            self._event_log.log("chat_assistant", session_id=ctx.session.session_id,
                           trace_id=trace_id, text=response)

        self._maybe_refresh_summary(ctx)

    # ── Command worker ───────────────────────────────────────────────────

    @work(exclusive=False, thread=True)
    async def _do_command(self, text: str) -> None:
        """Worker de comandos — executa dispatch em thread separada."""
        ctx = self.ctx
        if ctx is None or self._command_router is None:
            return

        result = self._command_router.dispatch(text, ctx)
        if result is False:
            self.exit()

    # ── Handlers de mensagens ───────────────────────────────────────────

    @on(ChatResponse)
    def handle_chat_response(self, event: ChatResponse) -> None:
        from cous.cli.tui.widgets.chat import ChatScroll
        scroll = self.query_one(ChatScroll)
        scroll.add_bubble(event.text, role="agent", trace_id=event.trace_id)

        # Atualizar StagesPanel
        stages = getattr(event, "stages", None) or []
        if stages:
            from cous.cli.tui.widgets.stages import StagesPanel
            try:
                panel = self.query_one(StagesPanel)
                panel.update(stages)
            except Exception:
                pass

    @on(StatusUpdated)
    def handle_status_updated(self, event: StatusUpdated) -> None:
        topbar = self.query_one(TopBar)
        topbar.update_status(event.state)

        from cous.cli.tui.widgets.status import StatusPanel
        try:
            status = self.query_one(StatusPanel)
            status.update_from_state(event.state)
        except Exception:
            pass

    @on(LogLineData)
    def handle_log_line(self, event: LogLineData) -> None:
        from cous.cli.tui.widgets.log_panel import LogPanel
        try:
            log = self.query_one(LogPanel)
            log.add_line(event.level, event.text)
        except Exception:
            pass

    # ── Handlers de dados (tabelas) ─────────────────────────────────────

    @on(SearchResultsData)
    def handle_search_results(self, event: SearchResultsData) -> None:
        rows = [
            f"{r.get('document_id', '')[:8]:<10} score={r.get('score', 0):.2f} {r.get('text', '')[:100]}"
            for r in (event.results or [])[:15]
        ]
        self._show_side_data("Busca", rows)

    @on(DocumentsData)
    def handle_documents(self, event: DocumentsData) -> None:
        rows = [
            f"{d.get('id', '')[:8]:<10} {d.get('title', '-')[:60]}"
            for d in (event.docs or [])[:15]
        ]
        self._show_side_data("Documentos", rows)

    @on(MeasurementsData)
    def handle_measurements(self, event: MeasurementsData) -> None:
        rows = []
        for s in (event.sessions or [])[:15]:
            h = s.get("header") or {}
            rows.append(
                f"{s.get('id', '')[:16]:<18} {h.get('fabricante', '-')} {h.get('modelo', '-')} {s.get('status', '-')}"
            )
        self._show_side_data("Medições", rows)

    @on(ChatSessionsData)
    def handle_chat_sessions(self, event: ChatSessionsData) -> None:
        rows = [
            f"{s.get('id', '')[:20]:<22} msgs={s.get('messages', 0)} {s.get('preview', '-')[:60]}"
            for s in (event.sessions or [])[:15]
        ]
        self._show_side_data("Sessões", rows)

    @on(MeasurementDetailData)
    def handle_measurement_detail(self, event: MeasurementDetailData) -> None:
        s = event.session or {}
        h = s.get("header") or {}
        rows = [
            f"ID: {s.get('id', '-')}",
            f"Status: {s.get('status', '-')}",
            f"Fabricante: {h.get('fabricante', '-')}",
            f"Modelo: {h.get('modelo', '-')}",
            f"Série: {h.get('numero_serie', '-')}",
            f"Snapshots: {s.get('total_snapshots', 0)}",
            f"Sync: {s.get('sync_status', '-')}",
        ]
        self._show_side_data("Medição", rows)

    def _show_side_data(self, title: str, rows: list[str]) -> None:
        from cous.cli.tui.widgets.sidebar import SidePanel
        try:
            panel = self.query_one(SidePanel)
            panel.show_data(title, rows)
        except Exception:
            pass

    # ── Helpers ─────────────────────────────────────────────────────────

    def _maybe_refresh_summary(self, ctx: object) -> None:
        limit = ctx.config.memory.max_chars_before_summary
        if ctx.session.pending_summary_chars() <= limit:
            return
        try:
            from cous.cli.commands import build_chat_summary
            summary = build_chat_summary(ctx)
            ctx.session.set_summary(summary)
            if self._event_log:
                self._event_log.log("summary_updated", session_id=ctx.session.session_id, automatic=True)
        except Exception:
            pass

    def action_focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def action_toggle_sidebar(self) -> None:
        try:
            sidebar = self.query_one(Sidebar)
            sidebar.display = not sidebar.display
        except Exception:
            pass

    def action_clear_chat(self) -> None:
        """Limpa o scroll do chat (Ctrl+R)."""
        try:
            from cous.cli.tui.widgets.chat import ChatScroll
            scroll = self.query_one(ChatScroll)
            scroll.clear()
        except Exception:
            pass

    def action_show_help(self) -> None:
        """Mostra lista de comandos no LogPanel (F1)."""
        if self._command_router:
            from cous.cli.tui.widgets.log_panel import LogPanel
            try:
                log = self.query_one(LogPanel)
                log.add_line("info", "── Comandos disponíveis ──")
                for name, desc in self._command_router.descriptions():
                    if desc.startswith("Atalho de"):
                        continue
                    log.add_line("info", f"  /{name:<14} {desc}")
            except Exception:
                pass

    @on(JobProgressData)
    def handle_job_progress(self, event: JobProgressData) -> None:
        from cous.cli.tui.widgets.log_panel import LogPanel
        try:
            log = self.query_one(LogPanel)
            log.add_line("info",
                f"job={event.job_id[:8]} status={event.status} stage={event.stage}")
        except Exception:
            pass

    @on(PromptRequest)
    def handle_prompt_request(self, event: PromptRequest) -> None:
        """Configura o InputBar para modo prompt."""
        self._active_prompt = event
        try:
            inp = self.query_one("#chat-input")
            placeholder = event.question
            if event.default:
                placeholder += f" [{event.default}]"
            inp.placeholder = placeholder
            inp.value = event.default
            inp.focus()
        except Exception:
            pass
