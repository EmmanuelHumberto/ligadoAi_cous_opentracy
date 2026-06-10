"""Mensagens Textual para comunicação entre componentes da TUI.

Toda comunicação entre workers assíncronos e widgets passa por mensagens
Textual (subclasses de Message). Isso garante thread-safety: workers
postam mensagens, o loop principal as entrega aos handlers @on().
"""

from __future__ import annotations

from textual.message import Message


class LogLineData(Message):
    """Linha de log para o LogPanel."""

    def __init__(self, level: str, text: str) -> None:
        self.level = level  # "error", "info", "success", "warning"
        self.text = text
        super().__init__()


class StatusTableData(Message):
    """Tabela de status para o StatusPanel."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self.rows = rows  # [(componente, estado, detalhe), ...]
        super().__init__()


class SearchResultsData(Message):
    """Resultados de busca para o SidePanel."""

    def __init__(self, results: list[dict]) -> None:
        self.results = results
        super().__init__()


class DocumentsData(Message):
    """Documentos indexados para o SidePanel."""

    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        super().__init__()


class MeasurementsData(Message):
    """Sessões de medição para o SidePanel."""

    def __init__(self, sessions: list[dict]) -> None:
        self.sessions = sessions
        super().__init__()


class MeasurementDetailData(Message):
    """Detalhe de uma medição para o SidePanel."""

    def __init__(self, session: dict) -> None:
        self.session = session
        super().__init__()


class ChatSessionsData(Message):
    """Sessões de chat para o SidePanel."""

    def __init__(self, sessions: list[dict]) -> None:
        self.sessions = sessions
        super().__init__()


class ChatResponse(Message):
    """Resposta do agente para o ChatPanel."""

    def __init__(self, text: str, trace_id: str = "",
                 stages: list[dict] | None = None,
                 token_count: int = 0) -> None:
        self.text = text
        self.trace_id = trace_id
        self.stages = stages or []
        self.token_count = token_count
        super().__init__()


class StatusUpdated(Message):
    """Status dos servidores atualizado (TopBar + StatusPanel)."""

    def __init__(self, state: "AppState") -> None:  # noqa: F821
        self.state = state
        super().__init__()


class FeedbackRegistered(Message):
    """Feedback registrado — flash notification."""

    def __init__(self, fb_type: str, trace_id: str) -> None:
        self.fb_type = fb_type  # "confirmed", "correction", "solution_applied"
        self.trace_id = trace_id
        super().__init__()


class JobProgressData(Message):
    """Progresso de job de indexação para o LogPanel."""

    def __init__(self, job_id: str, status: str, stage: str) -> None:
        self.job_id = job_id
        self.status = status  # "running", "indexed", "failed"
        self.stage = stage    # "convert", "embedding", "done"
        super().__init__()


class UserInput(Message):
    """Input do operador via InputBar."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()
