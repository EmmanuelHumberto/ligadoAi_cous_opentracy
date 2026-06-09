"""CLI entrypoint for the new Cous thin client."""

from __future__ import annotations

import argparse
from pathlib import Path

from cous.auth import AuthError, TokenProvider
from cous.bootstrap import bootstrap_auth
from cous.cli import renderer
from cous.cli.terminal import run_terminal
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.config import expand_path, load_config
from cous.application.session import ConversationStore
from cous.measurements.store import MeasurementLocalStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Cous thin client for OpenTracy")
    parser.add_argument("--mock", action="store_true", help="Reservado para clientes fake")
    parser.add_argument("--bootstrap", action="store_true", help="Reservado para bootstrap")
    parser.add_argument("--no-runtime", action="store_true", help="Nao inicia runtime local")
    parser.add_argument("--config", type=str, default=None, help="Caminho para config.toml")
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)
    if args.mock:
        renderer.warning("Modo mock ainda sera implementado com clientes fake.")
    if args.bootstrap:
        result = bootstrap_auth(config.auth)
        renderer.success(f"Token Cous: {result.token_file}")
        renderer.success(f"OpenTracy .env: {result.opentracy_env_file}")
        if result.token_created:
            renderer.info("Token novo gerado.")
        if result.env_updated:
            renderer.info("Reinicie o runtime do OpenTracy para carregar o novo token.")
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
    try:
        run_terminal(config, opentracy, knowledge, measurements, conversations)
    finally:
        opentracy.close()
        knowledge.close()
        measurements.close()


if __name__ == "__main__":
    main()
