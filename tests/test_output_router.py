"""Testes unitários para OutputRouter."""

import pytest
from unittest.mock import MagicMock

from cous.cli.tui.output_router import OutputRouter
from cous.cli.tui.events import InfoLine, TableData


class TestOutputRouter:
    def test_router_initialization(self):
        app = MagicMock()
        router = OutputRouter(app)
        assert router._pending == []

    def test_post_accumulates_when_not_running(self):
        app = MagicMock()
        app._running = False
        router = OutputRouter(app)
        router.error("test error")
        assert len(router._pending) == 1
        assert isinstance(router._pending[0], InfoLine)
        assert "test error" in router._pending[0].text

    def test_post_dispatches_when_running(self):
        app = MagicMock()
        app._running = True
        router = OutputRouter(app)
        router.error("test error")
        assert len(router._pending) == 0
        app.post_message.assert_called_once()

    def test_flush_pending(self):
        app = MagicMock()
        app._running = False
        router = OutputRouter(app)

        router.info("msg1")
        router.success("msg2")
        assert len(router._pending) == 2

        app._running = True
        router.flush_pending()
        assert len(router._pending) == 0
        assert app.post_message.call_count == 2

    # ── Todas as saídas viram InfoLine ──────────────────────────────────

    def test_error(self):
        app, router = self._make_running()
        router.error("algo deu errado")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "[red]" in msg.text
        assert "algo deu errado" in msg.text

    def test_info(self):
        app, router = self._make_running()
        router.info("info message")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "info message" in msg.text

    def test_success(self):
        app, router = self._make_running()
        router.success("ok")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "[green]" in msg.text

    def test_warning(self):
        app, router = self._make_running()
        router.warning("cuidado")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "[yellow]" in msg.text

    def test_assistant(self):
        app, router = self._make_running()
        router.assistant("resposta do agente")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "resposta do agente" in msg.text

    def test_welcome(self):
        app, router = self._make_running()
        router.welcome("test-agent")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "test-agent" in msg.text

    def test_status_table(self):
        app, router = self._make_running()
        rows = [("backend", "ok", "-"), ("runtime", "down", "-")]
        router.status_table(rows)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "Status" in msg.text
        assert "backend" in msg.text
        assert "runtime" in msg.text

    def test_search_results(self):
        app, router = self._make_running()
        results = [{"score": 1.0, "document_id": "abc123", "title": "Laudo #1", "text": "numero de serie 1212"}]
        router.search_results(results)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, TableData)
        assert msg.columns == ["Score", "ID", "Fonte", "Trecho"]
        assert len(msg.rows) == 1
        assert "abc123" in msg.rows[0][1]
        assert "1212" in msg.rows[0][3]

    def test_documents_table(self):
        app, router = self._make_running()
        docs = [{"id": "abc12345", "title": "Test"}]
        router.documents_table(docs)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, TableData)
        assert "ID" in msg.columns
        assert len(msg.rows) == 1
        assert "abc12345" in msg.rows[0][0]

    def test_measurements_table(self):
        app, router = self._make_running()
        sessions = [{"id": "m1", "status": "saved"}]
        router.measurements_table(sessions)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "Medições" in msg.text

    def test_chat_sessions_table(self):
        app, router = self._make_running()
        sessions = [{"session_id": "c1", "message_count": 3}]
        router.chat_sessions_table(sessions)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "Sessões" in msg.text

    def test_measurement_detail(self):
        app, router = self._make_running()
        session = {
            "id": "m1",
            "status": "saved",
            "header": {"fabricante": "FK", "modelo": "X1"},
        }
        router.measurement_detail(session)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, TableData)
        assert "Campo" in msg.columns
        assert "Valor" in msg.columns
        # Busca "FK" nos valores das linhas
        found = any("FK" in str(cell) for row in msg.rows for cell in row)
        assert found

    def test_clear(self):
        app, router = self._make_running()
        router.clear()
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert msg.clear is True

    def test_feedback_registered(self):
        app, router = self._make_running()
        router.feedback_registered("confirmed", "trace-001")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "Feedback" in msg.text
        assert "confirmed" in msg.text

    def test_job_progress(self):
        app, router = self._make_running()
        router.job_progress("job-001", "indexed", "done")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, InfoLine)
        assert "job-001" in msg.text
        assert "indexed" in msg.text

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_running():
        app = MagicMock()
        app._running = True
        router = OutputRouter(app)
        return app, router
