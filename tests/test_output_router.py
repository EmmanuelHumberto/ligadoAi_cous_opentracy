"""Testes unitários para OutputRouter."""

import pytest
from unittest.mock import MagicMock, patch

from cous.cli.tui.output_router import OutputRouter
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
        assert isinstance(router._pending[0], LogLineData)
        assert router._pending[0].level == "error"
        assert router._pending[0].text == "test error"

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

    # ── Mensagens de texto ──────────────────────────────────────────────

    def test_error(self):
        app, router = self._make_running()
        router.error("algo deu errado")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, LogLineData)
        assert msg.level == "error"
        assert msg.text == "algo deu errado"

    def test_info(self):
        app, router = self._make_running()
        router.info("info message")
        msg = app.post_message.call_args[0][0]
        assert msg.level == "info"

    def test_success(self):
        app, router = self._make_running()
        router.success("ok")
        msg = app.post_message.call_args[0][0]
        assert msg.level == "success"

    def test_warning(self):
        app, router = self._make_running()
        router.warning("cuidado")
        msg = app.post_message.call_args[0][0]
        assert msg.level == "warning"

    def test_assistant(self):
        app, router = self._make_running()
        router.assistant("resposta do agente")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, ChatResponse)
        assert msg.text == "resposta do agente"

    def test_welcome(self):
        app, router = self._make_running()
        router.welcome("test-agent")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, LogLineData)
        assert "test-agent" in msg.text

    # ── Tabelas ─────────────────────────────────────────────────────────

    def test_status_table(self):
        app, router = self._make_running()
        rows = [("backend", "ok", "-")]
        router.status_table(rows)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, StatusTableData)
        assert msg.rows == rows

    def test_search_results(self):
        app, router = self._make_running()
        results = [{"score": 1.0, "text": "test"}]
        router.search_results(results)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, SearchResultsData)
        assert msg.results == results

    def test_documents_table(self):
        app, router = self._make_running()
        docs = [{"id": "d1", "title": "Test"}]
        router.documents_table(docs)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, DocumentsData)
        assert msg.docs == docs

    def test_measurements_table(self):
        app, router = self._make_running()
        sessions = [{"id": "m1"}]
        router.measurements_table(sessions)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, MeasurementsData)
        assert msg.sessions == sessions

    def test_chat_sessions_table(self):
        app, router = self._make_running()
        sessions = [{"id": "c1", "messages": 3}]
        router.chat_sessions_table(sessions)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, ChatSessionsData)
        assert msg.sessions == sessions

    # ── Detalhes ────────────────────────────────────────────────────────

    def test_measurement_detail(self):
        app, router = self._make_running()
        session = {"id": "m1", "status": "saved"}
        router.measurement_detail(session)
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, MeasurementDetailData)
        assert msg.session == session

    # ── Controle ────────────────────────────────────────────────────────

    def test_clear(self):
        app, router = self._make_running()
        router.clear()
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, LogLineData)
        assert "---" in msg.text

    # ── Feedback ────────────────────────────────────────────────────────

    def test_feedback_registered(self):
        app, router = self._make_running()
        router.feedback_registered("confirmed", "trace-001")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, FeedbackRegistered)
        assert msg.fb_type == "confirmed"
        assert msg.trace_id == "trace-001"

    def test_job_progress(self):
        app, router = self._make_running()
        router.job_progress("job-001", "indexed", "done")
        msg = app.post_message.call_args[0][0]
        assert isinstance(msg, JobProgressData)
        assert msg.job_id == "job-001"
        assert msg.status == "indexed"
        assert msg.stage == "done"

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_running():
        app = MagicMock()
        app._running = True
        router = OutputRouter(app)
        return app, router
