"""CLI entrypoint for the new Cous thin client."""

from __future__ import annotations

import argparse
from pathlib import Path

from cous.application.feedback import FeedbackStore
from cous.application.session import ConversationStore
from cous.auth import AuthError, TokenProvider
from cous.bootstrap import bootstrap_auth
from cous.callback_server import start_background_callback_server
from cous.cli import renderer
from cous.cli.terminal import run_terminal
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.clients.system_prompt import SystemPromptCache
from cous.config import expand_path, load_config
from cous.logger import EventLogger, TraceEmitter
from cous.measurements.store import MeasurementLocalStore
from cous.mocks import (
    MockFeedbackStore,
    MockKnowledgeClient,
    MockMeasurementsClient,
    MockOpenTracyClient,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cous thin client for OpenTracy")
    parser.add_argument("--mock", action="store_true", help="Reservado para clientes fake")
    parser.add_argument("--bootstrap", action="store_true", help="Reservado para bootstrap")
    parser.add_argument(
        "--callback-server",
        action="store_true",
        help="Sobe servidor HTTP para callbacks de diagnostico do OpenTracy",
    )
    parser.add_argument(
        "--callback-host",
        default="127.0.0.1",
        help="Host do servidor de callback",
    )
    parser.add_argument(
        "--callback-port",
        type=int,
        default=8000,
        help="Porta do servidor de callback",
    )
    parser.add_argument("--config", type=str, default=None, help="Caminho para config.toml")
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)
    if args.callback_server:
        from cous.callback_server import run_callback_server

        run_callback_server(config, args.callback_host, args.callback_port)
        return

    if args.bootstrap:
        result = bootstrap_auth(config)
        renderer.success(f"Token Cous: {result.token_file}")
        renderer.success(f"Token API do agente: {result.api_token_file}")
        renderer.success(f"OpenTracy .env: {result.opentracy_env_file}")
        if result.token_created:
            renderer.info("Token novo gerado.")
        if result.api_token_created:
            renderer.info("Token do canal API salvo localmente.")
        if result.env_updated:
            renderer.info("Reinicie o runtime do OpenTracy para carregar o novo token.")
        if result.agent_created:
            renderer.info(f"Agente criado no runtime: {config.opentracy.agent_id}")
        if result.api_connected:
            renderer.info(f"Canal API pronto: {result.public_url}")
        else:
            renderer.warning(
                "Canal API nao foi conectado automaticamente; "
                "verifique se o runtime esta ativo."
            )
        return

    logger = EventLogger(
        expand_path(config.logs.events_file),
        max_bytes=config.logs.max_size_mb * 1024 * 1024,
        backup_count=config.logs.backup_count,
    )
    logger.log("startup", mock_mode=args.mock, agent_id=config.opentracy.agent_id)

    if args.mock:
        renderer.warning("Executando em modo mock: chat, knowledge e medicoes sem OpenTracy real.")
        opentracy = MockOpenTracyClient(agent_id=config.opentracy.agent_id)
        knowledge = MockKnowledgeClient()
        measurements = MockMeasurementsClient(
            MeasurementLocalStore(expand_path(config.measurements.storage_file))
        )
        conversations = ConversationStore(expand_path(config.chat.conversations_dir))
        feedback_store = MockFeedbackStore()
        trace_emitter = TraceEmitter(expand_path(config.logs.traces_file))
        system_prompt_cache = SystemPromptCache(client=opentracy, config=config.system_prompt)
        try:
            run_terminal(
                config, opentracy, knowledge, measurements, conversations, logger,
                feedback_store=feedback_store,
                system_prompt_cache=system_prompt_cache,
                trace_emitter=trace_emitter,
            )
        finally:
            opentracy.close()
            knowledge.close()
            measurements.close()
        return

    knowledge_token_provider = TokenProvider.for_knowledge(config.auth)
    api_token_provider = TokenProvider.for_api(config.auth)
    try:
        knowledge_token_provider.load()
    except AuthError as exc:
        renderer.error(str(exc))
        renderer.info(
            f"Configure {config.auth.env_var} ou crie o arquivo {config.auth.token_file}"
        )
        return
    try:
        api_token_provider.load()
    except AuthError as exc:
        renderer.error(str(exc))
        renderer.info(
            f"Configure {config.auth.api_env_var} ou crie o arquivo "
            f"{config.auth.api_token_file} para o chat do agente"
        )
        return

    opentracy = OpenTracyClient(config.opentracy, api_token_provider)
    knowledge = KnowledgeClient(config.opentracy, knowledge_token_provider)
    measurements = MeasurementsClient(
        config.opentracy,
        knowledge_token_provider,
        MeasurementLocalStore(expand_path(config.measurements.storage_file)),
    )
    conversations = ConversationStore(expand_path(config.chat.conversations_dir))
    feedback_store = FeedbackStore(expand_path(config.feedback.storage_file))
    trace_emitter = TraceEmitter(expand_path(config.logs.traces_file))
    system_prompt_cache = SystemPromptCache(client=opentracy, config=config.system_prompt)
    callback_server = start_background_callback_server(config)
    if callback_server is not None:
        renderer.info(f"Callback diagnostico v3 ativo em {callback_server.endpoint}")
    try:
        run_terminal(
            config, opentracy, knowledge, measurements, conversations, logger,
            feedback_store=feedback_store,
            system_prompt_cache=system_prompt_cache,
            trace_emitter=trace_emitter,
        )
    finally:
        opentracy.close()
        knowledge.close()
        measurements.close()
        if callback_server is not None:
            callback_server.stop()


if __name__ == "__main__":
    main()
