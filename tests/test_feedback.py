"""Testes unitários para comandos de feedback e componentes relacionados."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cous.application.feedback import FeedbackStore
from cous.application.session import ConversationStore
from cous.cli.commands import (
    _confirm_feedback,
    _correct_feedback,
    _solution_feedback,
    CommandContext,
)
from cous.logger import EventLogger
from cous.measurements.store import MeasurementLocalStore
from cous.mocks import MockKnowledgeClient, MockMeasurementsClient, MockOpenTracyClient


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_ctx(tmp_path: Path, *, with_chat: bool = False):
    """Cria CommandContext com FeedbackStore e mocks completos."""
    config = SimpleNamespace(
        opentracy=SimpleNamespace(agent_id="test", timeout=5),
        memory=SimpleNamespace(max_history=10, max_chars_before_summary=16000),
        knowledge=SimpleNamespace(poll_timeout_seconds=10),
    )
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    opentracy = MockOpenTracyClient(agent_id="test")
    knowledge = MockKnowledgeClient()
    measurements = MockMeasurementsClient(store)
    conversations = ConversationStore(tmp_path / "conversations")
    session = conversations.create_session()
    logger = EventLogger(tmp_path / "logs" / "events.jsonl")
    feedback_store = FeedbackStore(tmp_path / "feedback.jsonl")

    if with_chat:
        session.add("user", "qual o diagnostico da maquina?")
        session.add("assistant", "Diagnostico: trocar motor C16. Vibracao elevada.")
        opentracy.chat("qual o diagnostico da maquina?")
        ctx = CommandContext(
            config=config,
            opentracy=opentracy,
            knowledge=knowledge,
            measurements=measurements,
            conversations=conversations,
            session=session,
            logger=logger,
            feedback_store=feedback_store,
            system_prompt_cache=None,
            trace_emitter=None,
        )
        ctx.last_trace_id = "trace_abc123"
    else:
        ctx = CommandContext(
            config=config,
            opentracy=opentracy,
            knowledge=knowledge,
            measurements=measurements,
            conversations=conversations,
            session=session,
            logger=logger,
            feedback_store=feedback_store,
            system_prompt_cache=None,
            trace_emitter=None,
        )

    return ctx


# ── /confirmar ───────────────────────────────────────────────────────────


class TestConfirmFeedback:
    def test_confirm_last_response(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        result = _confirm_feedback(ctx, "")
        assert result is True
        records = ctx.feedback_store.list_records()
        assert len(records) == 1
        assert records[0].feedback_type == "confirmed"
        assert records[0].trace_id == "trace_abc123"
        assert records[0].original_response == "Diagnostico: trocar motor C16. Vibracao elevada."
        assert records[0].user_request == "qual o diagnostico da maquina?"

    def test_confirm_with_comment(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        _confirm_feedback(ctx, "resposta correta e bem estruturada")
        records = ctx.feedback_store.list_records()
        assert records[0].content == "resposta correta e bem estruturada"
        assert records[0].user_request == "qual o diagnostico da maquina?"

    def test_confirm_with_explicit_trace_id(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        ctx.last_trace_id = "trace_xyz"  # diferente do que vamos passar
        _confirm_feedback(ctx, "07030490-25d5-4e7b-a690-4da4d9583080 confirmando trace antigo")
        records = ctx.feedback_store.list_records()
        assert records[0].trace_id == "07030490-25d5-4e7b-a690-4da4d9583080"
        assert "confirmando trace antigo" in records[0].content

    def test_confirm_with_mock_trace_id(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        _confirm_feedback(ctx, "mock_04ab6ea08e7c trace mock confirmado")
        records = ctx.feedback_store.list_records()
        assert records[0].trace_id == "mock_04ab6ea08e7c"

    def test_confirm_with_trace_id_no_comment(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        _confirm_feedback(ctx, "07030490-25d5-4e7b-a690-4da4d9583080")
        records = ctx.feedback_store.list_records()
        assert records[0].trace_id == "07030490-25d5-4e7b-a690-4da4d9583080"
        # comment deve cair no fallback da last_assistant_message
        assert len(records[0].content) > 0

    def test_confirm_without_feedback_store(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        ctx.feedback_store = None
        result = _confirm_feedback(ctx, "")
        assert result is True  # não quebra

    def test_confirm_without_chat_history(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=False)
        ctx.last_trace_id = ""
        result = _confirm_feedback(ctx, "confirmando sem historico")
        assert result is True
        # sem trace_id e sem resposta anterior → não registra nada
        records = ctx.feedback_store.list_records()
        assert len(records) == 0


# ── /corrigir ────────────────────────────────────────────────────────────


class TestCorrectFeedback:
    def test_correct_records_feedback(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        _correct_feedback(ctx, "nao era motor C16, era C27")
        records = ctx.feedback_store.list_records()
        assert len(records) == 1
        assert records[0].feedback_type == "correction"
        assert records[0].content == "nao era motor C16, era C27"
        assert records[0].original_response == "Diagnostico: trocar motor C16. Vibracao elevada."
        assert records[0].user_request == "qual o diagnostico da maquina?"

    def test_correct_empty_args_shows_error(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        result = _correct_feedback(ctx, "")
        assert result is True
        records = ctx.feedback_store.list_records()
        assert len(records) == 0

    def test_correct_without_feedback_store(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.feedback_store = None
        _correct_feedback(ctx, "correcao qualquer")
        # não quebra


# ── /solucao ─────────────────────────────────────────────────────────────


class TestSolutionFeedback:
    def test_solution_records_feedback(self, tmp_path):
        ctx = _make_ctx(tmp_path, with_chat=True)
        _solution_feedback(ctx, "troquei a fonte e resolveu")
        records = ctx.feedback_store.list_records()
        assert len(records) == 1
        assert records[0].feedback_type == "solution_applied"
        assert records[0].content == "troquei a fonte e resolveu"
        assert records[0].user_request == "qual o diagnostico da maquina?"

    def test_solution_empty_args_shows_error(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        result = _solution_feedback(ctx, "")
        assert result is True
        records = ctx.feedback_store.list_records()
        assert len(records) == 0


# ── FeedbackStore ────────────────────────────────────────────────────────


class TestFeedbackStore:
    def test_record_and_list(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.jsonl")
        store.record(
            feedback_type="confirmed",
            session_id="s1",
            trace_id="t1",
            content="bom",
            original_response="resp",
            user_request="pergunta",
        )
        records = store.list_records()
        assert len(records) == 1
        assert records[0].user_request == "pergunta"

    def test_export_as_goldens_correct_semantics(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.jsonl")
        store.record(
            feedback_type="confirmed",
            session_id="s1",
            trace_id="t1",
            content="comentario do operador",
            original_response="resposta do agente",
            user_request="pergunta original do usuario",
        )
        out = tmp_path / "goldens.jsonl"
        count = store.export_as_goldens(out)
        assert count == 1

        line = json.loads(out.read_text().strip())
        # question deve ser a pergunta do usuário, expected a resposta do agente
        assert line["question"] == "pergunta original do usuario"
        assert line["expected"] == "resposta do agente"
        assert line["source"] == "terminal_feedback"

    def test_export_fallback_when_no_user_request(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.jsonl")
        store.record(
            feedback_type="confirmed",
            session_id="s1",
            trace_id="t1",
            content="comentario",
            original_response="resposta agente",
            user_request="",  # sem user_request
        )
        out = tmp_path / "goldens.jsonl"
        count = store.export_as_goldens(out)
        assert count == 1
        line = json.loads(out.read_text().strip())
        # fallback: usa original_response como question
        assert line["question"] == "resposta agente"
        assert line["expected"] == "resposta agente"

    def test_list_filters_by_type(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.jsonl")
        store.record(feedback_type="confirmed", session_id="s1", content="ok")
        store.record(feedback_type="correction", session_id="s1", content="errado")
        assert len(store.list_records(feedback_type="confirmed")) == 1
        assert len(store.list_records(feedback_type="correction")) == 1
        assert len(store.list_records()) == 2

    def test_tolerates_corrupted_line(self, tmp_path):
        path = tmp_path / "fb.jsonl"
        path.write_text('{"invalid json\n{"feedback_type": "confirmed", ...}\n', encoding="utf-8")
        store = FeedbackStore(path)
        records = store.list_records()
        assert len(records) == 0  # linha corrompida ignorada


# ── Session: last_user_message ───────────────────────────────────────────


class TestSessionLastUserMessage:
    def test_returns_last_user_message(self, tmp_path):
        store = ConversationStore(tmp_path / "conv")
        session = store.create_session()
        session.add("user", "primeira pergunta")
        session.add("assistant", "primeira resposta")
        session.add("user", "segunda pergunta")
        assert session.last_user_message() == "segunda pergunta"

    def test_returns_empty_when_no_user_message(self, tmp_path):
        store = ConversationStore(tmp_path / "conv")
        session = store.create_session()
        assert session.last_user_message() == ""
