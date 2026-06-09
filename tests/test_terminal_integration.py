"""Testes end-to-end do loop run_terminal com clientes mock.

Estes testes requerem TTY interativo. Em CI, são excluídos via:
    pytest -m "not terminal"
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from cous.application.session import ConversationStore
from cous.cli.terminal import run_terminal
from cous.mocks import MockKnowledgeClient, MockMeasurementsClient, MockOpenTracyClient
from cous.measurements.store import MeasurementLocalStore

pytestmark = pytest.mark.terminal


def make_mock_config(tmp_path):
    """Retorna config mínima com diretórios temporários."""
    return SimpleNamespace(
        opentracy=SimpleNamespace(agent_id="test_agent"),
        memory=SimpleNamespace(max_history=10, max_chars_before_summary=16000),
        chat=SimpleNamespace(conversations_dir=str(tmp_path / "conversations")),
        measurements=SimpleNamespace(storage_file=str(tmp_path / "measurements.json")),
        logs=SimpleNamespace(events_file=str(tmp_path / "logs/events.jsonl")),
        knowledge=SimpleNamespace(poll_timeout_seconds=10),
    )


@pytest.fixture()
def mock_env(tmp_path):
    config = make_mock_config(tmp_path)
    opentracy = MockOpenTracyClient(agent_id="test_agent")
    knowledge = MockKnowledgeClient()
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    measurements = MockMeasurementsClient(store)
    conversations = ConversationStore(tmp_path / "conversations")
    logger = SimpleNamespace(log=lambda *a, **kw: None)
    return config, opentracy, knowledge, measurements, conversations, logger


def simulate_terminal(mock_env, commands: list[str]) -> None:
    """Executa o terminal com sequência de comandos injetados."""
    config, opentracy, knowledge, measurements, conversations, logger = mock_env
    inputs = iter(commands + ["/sair"])
    with patch("builtins.input", side_effect=inputs):
        run_terminal(config, opentracy, knowledge, measurements, conversations, logger)


def test_terminal_startup_and_exit(mock_env):
    simulate_terminal(mock_env, [])


def test_terminal_free_chat(mock_env):
    simulate_terminal(mock_env, ["olá, qual o status?"])


def test_terminal_novo_e_listar(mock_env):
    simulate_terminal(mock_env, ["/novo", "/listar"])


def test_terminal_resumo(mock_env):
    simulate_terminal(mock_env, ["mensagem 1", "mensagem 2", "/resumo"])


def test_terminal_medicoes(mock_env):
    simulate_terminal(mock_env, ["/medicoes"])


def test_terminal_capturar_sem_serial(mock_env):
    simulate_terminal(mock_env, [
        "/capturar fabricante=Test modelo=X serie=S1 verticais=hall,power sem_serial=sim duracao=5"
    ])
