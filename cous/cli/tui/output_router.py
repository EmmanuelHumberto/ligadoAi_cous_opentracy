"""Roteador de saída para painéis TUI.

Redireciona TODAS as chamadas de renderer para widgets Textual.
Thread-safe: acumula mensagens em _pending antes do on_mount(),
despacha via post_message após o loop de eventos iniciar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.message import Message

from cous.cli.tui.events import (
    ChatResponse,
    ChatSessionsData,
    DocumentsData,
    FeedbackRegistered,
    JobProgressData,
    LogLineData,
    MeasurementDetailData,
    MeasurementsData,
    SearchResultsData,
    StatusTableData,
)


class OutputRouter:
    """Redireciona saídas do renderer para widgets Textual.

    Usa fila interna para mensagens pré-mount e guard _running
    para post_message seguro após o loop de eventos iniciar.
    """

    def __init__(self, app: object) -> None:
        self._app = app
        self._pending: list[Message] = []

    # ── Core ────────────────────────────────────────────────────────────

    def _post(self, msg: Message) -> None:
        """Posta mensagem se o app está rodando, senão acumula."""
        running = getattr(self._app, "_running", False)
        if running:
            self._app.post_message(msg)
        else:
            self._pending.append(msg)

    def flush_pending(self) -> None:
        """Despacha mensagens acumuladas antes do on_mount."""
        for msg in self._pending:
            self._app.post_message(msg)
        self._pending.clear()

    # ── Mensagens de texto ──────────────────────────────────────────────

    def error(self, text: str) -> None:
        self._post(LogLineData(level="error", text=text))

    def info(self, text: str) -> None:
        self._post(LogLineData(level="info", text=text))

    def success(self, text: str) -> None:
        self._post(LogLineData(level="success", text=text))

    def warning(self, text: str) -> None:
        self._post(LogLineData(level="warning", text=text))

    def assistant(self, text: str) -> None:
        self._post(ChatResponse(text=text))

    def welcome(self, agent_id: str) -> None:
        self._post(LogLineData(
            level="info",
            text=f"Cous TUI — agente: {agent_id}",
        ))

    # ── Tabelas ─────────────────────────────────────────────────────────

    def status_table(self, rows: list[tuple[str, str, str]]) -> None:
        self._post(StatusTableData(rows))

    def search_results(self, results: list[dict]) -> None:
        self._post(SearchResultsData(results))

    def documents_table(self, docs: list[dict]) -> None:
        self._post(DocumentsData(docs))

    def measurements_table(self, sessions: list[dict]) -> None:
        self._post(MeasurementsData(sessions))

    def chat_sessions_table(self, sessions: list[dict]) -> None:
        self._post(ChatSessionsData(sessions))

    # ── Detalhes ────────────────────────────────────────────────────────

    def measurement_detail(self, session: dict) -> None:
        self._post(MeasurementDetailData(session))

    # ── Controle ────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._post(LogLineData(level="info", text="--- tela limpa ---"))

    # ── Feedback ────────────────────────────────────────────────────────

    def feedback_registered(self, fb_type: str, trace_id: str) -> None:
        self._post(FeedbackRegistered(fb_type, trace_id))

    def job_progress(self, job_id: str, status: str, stage: str) -> None:
        self._post(JobProgressData(job_id, status, stage))
