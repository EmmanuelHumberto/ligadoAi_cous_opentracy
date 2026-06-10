"""Fixtures compartilhadas para testes do Cous."""

from types import SimpleNamespace

import pytest

from cous.application.session import ConversationStore
from cous.cli.commands import CommandContext
from cous.logger import EventLogger
from cous.measurements.store import MeasurementLocalStore
from cous.mocks import MockKnowledgeClient, MockMeasurementsClient, MockOpenTracyClient


@pytest.fixture()
def make_context(tmp_path):
    """Factory que retorna CommandContext populado com mocks reais."""

    def _factory():
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
        return CommandContext(
            config=config,
            opentracy=opentracy,
            knowledge=knowledge,
            measurements=measurements,
            conversations=conversations,
            session=session,
            logger=logger,
            feedback_store=None,
            system_prompt_cache=None,
            trace_emitter=None,
        )

    return _factory
